# Tube Grab - Copyright (C) 2026 AutomationGod
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tube Grab by AutomationGod: local YouTube downloader (MP3, M4A, MP4) with playlists
and a fast MP3 clip trimmer.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional, Tuple
from urllib.parse import parse_qs, urlparse
import urllib.request

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
TEMP_ROOT = APP_DIR / "temp"
STATIC_DIR = APP_DIR / "static"
DOWNLOAD_SETTINGS_PATH = APP_DIR / "download_settings.json"

SESSION_TTL_SEC = 2 * 60 * 60  # 2 hours
METADATA_TIMEOUT = 90
DOWNLOAD_TIMEOUT = 3600
# Faster DASH/HLS per file (YouTube). See yt-dlp -N / --concurrent-fragments.
YTDLP_CONCURRENT_FRAGMENTS = 4
# What the in-app updater installs. The "default" extra adds yt-dlp-ejs, which yt-dlp needs
# (with a JS runtime such as Deno) to solve YouTube's JavaScript challenges.
YTDLP_PIP_REQUIREMENT = "yt-dlp[default]"

_ytdlp_cmd_cache: Optional[list[str]] = None
_ytdlp_probe_failed: bool = False


def _project_venv_python() -> Optional[Path]:
    if sys.platform == "win32":
        p = APP_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        p = APP_DIR / ".venv" / "bin" / "python"
    return p if p.is_file() else None


def _venv_can_import_ytdlp(py: Path) -> bool:
    try:
        r = subprocess.run(
            [str(py), "-c", "import yt_dlp"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ytdlp_cmd() -> list[str]:
    """Resolve how to run yt-dlp: PATH CLI, current Python, or project .venv (IDE often uses system Python)."""
    global _ytdlp_cmd_cache, _ytdlp_probe_failed
    if _ytdlp_cmd_cache is not None:
        return _ytdlp_cmd_cache
    if _ytdlp_probe_failed:
        return []

    if shutil.which("yt-dlp"):
        _ytdlp_cmd_cache = ["yt-dlp"]
        return _ytdlp_cmd_cache
    if importlib.util.find_spec("yt_dlp") is not None:
        _ytdlp_cmd_cache = [sys.executable, "-m", "yt_dlp"]
        return _ytdlp_cmd_cache

    venv_py = _project_venv_python()
    if venv_py is not None and _venv_can_import_ytdlp(venv_py):
        _ytdlp_cmd_cache = [str(venv_py), "-m", "yt_dlp"]
        return _ytdlp_cmd_cache

    _ytdlp_probe_failed = True
    return []


def ensure_tools() -> None:
    if not _ytdlp_cmd():
        venv_hint = _project_venv_python()
        extra = ""
        if venv_hint is None:
            extra = f"\nCreate a venv in the app folder: cd {APP_DIR} && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
        else:
            extra = f"\nInstall into project venv: {venv_hint} -m pip install -r {APP_DIR / 'requirements.txt'}"
        raise RuntimeError(
            "Missing yt-dlp. Pick one:\n"
            f"  • {sys.executable} -m pip install yt-dlp\n"
            "  • brew install yt-dlp   (or another global yt-dlp on PATH)\n"
            f"  • pip install -r requirements.txt inside ./.venv{extra}"
        )
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("Missing `ffmpeg` on PATH. Install: brew install ffmpeg")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("Missing `ffprobe` on PATH. Install: brew install ffmpeg")


@dataclass
class Session:
    id: str
    created: float
    full_path: Path  # first file (clips use this when len(paths)==1)
    title: str
    duration_sec: float
    thumbnail: Optional[str]
    media_format: str  # "mp3" | "m4a" | "mp4"
    media_paths: List[Path] = field(default_factory=list)
    media_titles: List[str] = field(default_factory=list)

    clip_paths: dict[str, Path] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.media_paths:
            self.media_paths = [self.full_path]
        if not self.media_titles:
            self.media_titles = [self.title]


sessions: dict[str, Session] = {}
SESSION_LOCK = threading.RLock()

def _get_session(session_id: str) -> Optional[Session]:
    with SESSION_LOCK:
        return sessions.get(session_id)


def _store_session(session: Session) -> None:
    with SESSION_LOCK:
        sessions[session.id] = session


def _cleanup_expired_sessions() -> None:
    now = time.time()
    dead: list[str] = []
    with SESSION_LOCK:
        for sid, s in sessions.items():
            if now - s.created > SESSION_TTL_SEC:
                dead.append(sid)
    for sid in dead:
        _destroy_session(sid)


def _destroy_session(session_id: str) -> None:
    with SESSION_LOCK:
        s = sessions.pop(session_id, None)
    if not s:
        return
    d = s.full_path.parent
    if d.is_dir() and d.resolve() == (TEMP_ROOT / session_id).resolve():
        shutil.rmtree(d, ignore_errors=True)


def _youtube_url_ok(url: str) -> bool:
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        return False
    # Accept any /watch?… query (v= and list= can appear in either order; index= is playlist context).
    return bool(
        re.search(
            r"(?:youtube\.com/watch\?|youtu\.be/|youtube\.com/shorts/|youtube\.com/playlist\?)",
            u,
        )
    )


def _youtube_url_query_dict(url: str) -> dict[str, list[str]]:
    try:
        return parse_qs(urlparse(url.strip()).query, keep_blank_values=False)
    except (ValueError, OSError):
        return {}


def _youtube_list_param(url: str) -> Optional[str]:
    for key, vals in _youtube_url_query_dict(url).items():
        if key.lower() == "list" and vals and vals[0].strip():
            return vals[0].strip()
    return None


def _youtube_index_param(url: str) -> Optional[int]:
    for key, vals in _youtube_url_query_dict(url).items():
        if key.lower() != "index" or not vals:
            continue
        try:
            return int(str(vals[0]).strip())
        except ValueError:
            return None
    return None


def _youtube_video_id(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None


def _youtube_playlist_url_from_list_id(list_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={list_id}"


PLAYLIST_FLAT_MAX = 200


def _run_ytdlp_playlist_flat(
    url: str, timeout: int, *, playlist_end: Optional[int] = None
) -> dict[str, Any]:
    end = PLAYLIST_FLAT_MAX if playlist_end is None else playlist_end
    cmd = [
        *_ytdlp_cmd(),
        "--flat-playlist",
        "-J",
        "--no-download",
        "--playlist-end",
        str(end),
        url.strip(),
    ]
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        raw = (p.stderr or p.stdout or "").strip() or "yt-dlp failed"
        raise HTTPException(status_code=400, detail=humanize_ytdlp_error(raw))
    out = (p.stdout or "").strip()
    if not out:
        raise HTTPException(status_code=400, detail="No playlist data from yt-dlp")
    return json.loads(out)


def humanize_ytdlp_error(text: str) -> str:
    """Short user-facing message for common yt-dlp failures."""
    low = text.lower()
    if "sign in to confirm" in low or "not a bot" in low or "inappropriate for some users" in low:
        return (
            "YouTube wants sign-in or thinks the request is automated. "
            'Try: pip install -U "yt-dlp[default]" — or use cookies (see yt-dlp README).'
        )
    if "private video" in low:
        return "This video is private."
    if "members only" in low:
        return "Members-only video; sign-in/cookies required."
    if "age-restricted" in low or "age restricted" in low:
        return "Age-restricted video; yt-dlp may need account cookies."
    if "video unavailable" in low or "this video is not available" in low:
        return "Video unavailable (removed, private, or blocked)."
    if "not available in your country" in low or "region" in low and "blocked" in low:
        return "Not available in your region."
    if "http error 403" in low or " 403 " in low:
        return 'Access denied (403). Update yt-dlp: pip install -U "yt-dlp[default]"'
    if "http error 429" in low or " 429 " in low:
        return "Too many requests — wait a bit and try again."
    if "live stream" in low or "premiere" in low:
        return "Live or premiere content may not download until it ends."
    if "copyright" in low and "blocked" in low:
        return "Blocked for copyright in your region."
    first = text.strip().split("\n")[0].strip()
    return (first[:450] + "…") if len(first) > 450 else (first or "yt-dlp failed.")


def humanize_ffmpeg_error(text: str) -> str:
    low = text.lower()
    if "invalid argument" in low or "invalid data" in low:
        return "ffmpeg could not cut at those times (try slightly different start/end)."
    if "no such file" in low:
        return "Source file missing; prepare the download again."
    first = text.strip().split("\n")[0].strip()
    return (first[:400] + "…") if len(first) > 400 else (first or "ffmpeg failed.")


def parse_timestamp(s: str) -> float:
    s = s.strip()
    if not s:
        raise ValueError("Empty timestamp")
    parts = s.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError("Use MM:SS or HH:MM:SS")


def _run_ytdlp_json(url: str, timeout: int) -> dict[str, Any]:
    cmd = [
        *_ytdlp_cmd(),
        "--no-playlist",
        "--dump-json",
        "--no-download",
        url.strip(),
    ]
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        raw = (p.stderr or p.stdout or "").strip() or "yt-dlp failed"
        raise HTTPException(status_code=400, detail=humanize_ytdlp_error(raw))
    line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
    if not line:
        raise HTTPException(status_code=400, detail="No metadata from yt-dlp")
    return json.loads(line)


def _run_ytdlp_download(url: str, out_dir: Path, media_format: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / "full.%(ext)s")
    base = _ytdlp_cmd()
    if media_format == "mp3":
        cmd = [
            *base,
            "-N",
            str(YTDLP_CONCURRENT_FRAGMENTS),
            "--no-playlist",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "-o",
            out_tmpl,
            url.strip(),
        ]
    elif media_format == "m4a":
        # Keep YouTube's AAC stream as-is; -x only converts if no m4a stream exists.
        cmd = [
            *base,
            "-N",
            str(YTDLP_CONCURRENT_FRAGMENTS),
            "--no-playlist",
            "-f",
            "ba[ext=m4a]/ba",
            "-x",
            "--audio-format",
            "m4a",
            "--audio-quality",
            "0",
            "-o",
            out_tmpl,
            url.strip(),
        ]
    else:
        cmd = [
            *base,
            "-N",
            str(YTDLP_CONCURRENT_FRAGMENTS),
            "--no-playlist",
            "-f",
            "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "-o",
            out_tmpl,
            url.strip(),
        ]
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=DOWNLOAD_TIMEOUT,
    )
    if p.returncode != 0:
        raw = (p.stderr or p.stdout or "").strip() or "Download failed"
        raise HTTPException(status_code=400, detail=humanize_ytdlp_error(raw))
    candidates = list(out_dir.glob(f"full.{media_format}"))
    if not candidates:
        candidates = list(out_dir.glob("full.*"))
    if not candidates:
        raise HTTPException(status_code=500, detail="Download finished but file not found")
    return candidates[0]


def _run_ytdlp_download_playlist(
    url: str,
    out_dir: Path,
    media_format: str,
    playlist_items: Optional[str],
    timeout: int,
) -> Tuple[List[Path], Optional[str]]:
    """Download playlist (or subset). Skips unavailable entries; returns (paths, warning_if_any_errors)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / "%(playlist_index)03d - %(title)s.%(ext)s")
    base = _ytdlp_cmd()
    cmd: List[str] = [
        *base,
        "-N",
        str(YTDLP_CONCURRENT_FRAGMENTS),
        "--ignore-errors",
        "-o",
        out_tmpl,
        url.strip(),
    ]
    if playlist_items and playlist_items.strip():
        cmd.extend(["--playlist-items", playlist_items.strip()])
    if media_format == "mp3":
        cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", "0"])
    elif media_format == "m4a":
        cmd.extend(["-f", "ba[ext=m4a]/ba", "-x", "--audio-format", "m4a", "--audio-quality", "0"])
    else:
        cmd.extend(["-f", "bv*+ba/b", "--merge-output-format", "mp4"])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    ext = media_format if media_format in ("mp3", "m4a") else "mp4"
    paths = sorted(out_dir.glob(f"*.{ext}"))
    if not paths:
        paths = sorted(
            [x for x in out_dir.iterdir() if x.is_file() and x.suffix.lower() in (".mp3", ".mp4", ".webm", ".m4a")]
        )
    if paths:
        warning: Optional[str] = None
        if p.returncode != 0:
            warning = (
                "Some videos were skipped (unavailable, private, or blocked). "
                f"Downloaded {len(paths)} file(s). If you expected more, update yt-dlp or check the playlist."
            )
        return paths, warning
    raw = (p.stderr or p.stdout or "").strip() or "Download failed"
    raise HTTPException(status_code=400, detail=humanize_ytdlp_error(raw))


def _expand_playlist_items_spec(spec: str) -> List[int]:
    """Parse yt-dlp ``--playlist-items`` (e.g. ``17-30``, ``1,3,5-8``) into 1-based indices."""
    out: List[int] = []
    seen: set[int] = set()
    for raw_part in spec.replace(" ", "").split(","):
        if not raw_part:
            continue
        if "-" in raw_part:
            bounds = raw_part.split("-", 1)
            if len(bounds) != 2:
                continue
            try:
                lo, hi = int(bounds[0]), int(bounds[1])
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            for i in range(lo, hi + 1):
                if i not in seen:
                    seen.add(i)
                    out.append(i)
        else:
            try:
                i = int(raw_part)
            except ValueError:
                continue
            if i not in seen:
                seen.add(i)
                out.append(i)
    return out


def _playlist_output_indices_from_paths(paths: List[Path]) -> set[int]:
    """Indices from output template ``%(playlist_index)03d - %(title)s``."""
    got: set[int] = set()
    for p in paths:
        m = re.match(r"^(\d+)\s*-\s", p.stem)
        if m:
            got.add(int(m.group(1)))
    return got


def _ffprobe_duration_seconds(path: Path) -> float:
    if not path.is_file():
        return 0.0
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if p.returncode != 0:
        return 0.0
    try:
        return float((p.stdout or "0").strip())
    except ValueError:
        return 0.0


def _parse_playlist_flat_entries(data: dict[str, Any]) -> Tuple[str, List[dict[str, Any]]]:
    title = data.get("title") or data.get("playlist_title") or "Playlist"
    raw = data.get("entries") or []
    entries: List[dict[str, Any]] = []
    for i, e in enumerate(raw, start=1):
        if not isinstance(e, dict):
            continue
        vid = e.get("id")
        if not vid and e.get("url"):
            vm = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", str(e.get("url", "")))
            vid = vm.group(1) if vm else None
        entries.append(
            {
                "index": i,
                "id": vid,
                "title": e.get("title") or (f"Video {i}" if vid else "Unknown"),
                "duration_sec": float(e["duration"]) if e.get("duration") is not None else None,
                "url": f"https://www.youtube.com/watch?v={vid}" if vid else e.get("url"),
            }
        )
    return title, entries


def _ffmpeg_trim_copy(src: Path, dst: Path, start_sec: float, duration_sec: float) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        str(src),
        "-t",
        f"{duration_sec:.3f}",
        "-c",
        "copy",
        str(dst),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raw = (p.stderr or p.stdout or "").strip() or "ffmpeg failed"
        raise HTTPException(status_code=400, detail=humanize_ffmpeg_error(raw))


def _safe_filename_base(name: str) -> str:
    name = re.sub(r'[^\w\s\-().]', "", name).strip()
    name = re.sub(r"\s+", "_", name)
    return name[:120] if name else "clip"


def _media_type(media_format: str) -> str:
    """Content-Type for a prepared session file."""
    return {"mp3": "audio/mpeg", "m4a": "audio/mp4"}.get(media_format, "video/mp4")


def _session_clips_subdir_name(s: Session) -> str:
    """Subfolder under the save directory: `{sanitized_track_or_title}_clips`."""
    label = ""
    if s.media_titles and str(s.media_titles[0]).strip():
        label = _safe_filename_base(str(s.media_titles[0]).strip())
    if not label:
        label = _safe_filename_base((s.title or "").strip())
    if not label:
        label = "track"
    return f"{label}_clips"


def _read_saved_download_dir_raw() -> str:
    if not DOWNLOAD_SETTINGS_PATH.is_file():
        return ""
    try:
        data = json.loads(DOWNLOAD_SETTINGS_PATH.read_text(encoding="utf-8"))
        d = data.get("download_dir")
        return d.strip() if isinstance(d, str) else ""
    except (json.JSONDecodeError, OSError):
        return ""


def _pick_folder_macos() -> Optional[str]:
    p = subprocess.run(
        [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Tube Grab — choose save folder (e.g. Dropbox)")',
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if p.returncode != 0:
        return None
    line = (p.stdout or "").strip()
    return line or None


def _pick_folder_linux_zenity() -> Optional[str]:
    """Zenity only; caller must check which('zenity') first."""
    p = subprocess.run(
        ["zenity", "--file-selection", "--directory", "--title=Tube Grab — save folder"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if p.returncode != 0:
        return None
    line = (p.stdout or "").strip()
    return line or None


def _pick_folder_tk() -> Optional[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update_idletasks()
    try:
        path = filedialog.askdirectory(title="Tube Grab — save folder (e.g. Dropbox)")
    finally:
        root.destroy()
    return path.strip() if path else None


def native_pick_folder() -> Optional[str]:
    """Open a native folder dialog. Returns None if cancelled or dialog failed."""
    if sys.platform == "darwin":
        return _pick_folder_macos()
    if sys.platform == "linux":
        if shutil.which("zenity"):
            return _pick_folder_linux_zenity()
        return _pick_folder_tk()
    if sys.platform == "win32":
        return _pick_folder_tk()
    return _pick_folder_tk()


def download_folder_settings() -> dict[str, Any]:
    """Persisted folder for server-side copies (e.g. Dropbox)."""
    raw = _read_saved_download_dir_raw()
    if not raw:
        return {"download_dir": "", "folder_ok": False, "resolved_path": None}
    try:
        p = Path(raw).expanduser().resolve()
    except OSError:
        return {"download_dir": raw, "folder_ok": False, "resolved_path": None}
    ok = p.is_dir() and os.access(p, os.W_OK)
    return {
        "download_dir": raw,
        "folder_ok": ok,
        "resolved_path": str(p) if ok else None,
    }


def _copy_to_saved_folder(src: Path, filename: str) -> None:
    info = download_folder_settings()
    if not info.get("folder_ok") or not info.get("resolved_path"):
        return
    dest_dir = Path(info["resolved_path"])
    safe_name = Path(filename).name or src.name
    dest = dest_dir / safe_name
    try:
        shutil.copy2(src, dest)
    except OSError:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    try:
        ensure_tools()
    except RuntimeError as e:
        print(f"WARNING: {e}")
    yield


app = FastAPI(
    title="Tube Grab",
    description="Local YouTube downloader (MP3, M4A, MP4) with playlists and fast MP3 clips. By AutomationGod.",
    version="1.0",
    license_info={"name": "GPL-3.0-or-later", "identifier": "GPL-3.0-or-later"},
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MetadataBody(BaseModel):
    url: str


class PrepareBody(BaseModel):
    url: str
    format: str = Field(default="mp3", description="mp3, m4a or mp4")
    previous_session_id: Optional[str] = None
    playlist_mode: Literal["single", "all", "items"] = "single"
    playlist_items: Optional[str] = Field(
        default=None,
        description='yt-dlp --playlist-items spec, e.g. "1,3,5-8" when playlist_mode=items',
    )


class PlaylistInfoBody(BaseModel):
    url: str


class ClipBody(BaseModel):
    start: str
    end: Optional[str] = None
    duration_sec: Optional[float] = None
    name: Optional[str] = None


class DownloadFolderBody(BaseModel):
    download_dir: str = Field(default="", description="Absolute folder path; empty string clears")


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        return HTMLResponse("<p>Missing static/index.html</p>", status_code=500)
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/api/health")
async def api_health() -> JSONResponse:
    yc = _ytdlp_cmd()
    ytdlp_ok = bool(yc)
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    via: Optional[str] = None
    if yc:
        if yc == ["yt-dlp"]:
            via = "cli_path"
        elif len(yc) >= 2 and yc[-2:] == ["-m", "yt_dlp"]:
            exe = yc[0].replace("\\", "/").lower()
            if ".venv" in exe and ("bin/python" in exe or "/scripts/python" in exe):
                via = "project_venv"
            else:
                via = "python_module"
    return JSONResponse(
        {
            "ok": ytdlp_ok and ffmpeg_ok,
            "ytdlp": ytdlp_ok,
            "ffmpeg": ffmpeg_ok,
            "ytdlp_via": via,
            "python": sys.executable,
        }
    )


@app.delete("/api/session/{session_id}")
async def abandon_session(session_id: str) -> JSONResponse:
    _destroy_session(session_id)
    return JSONResponse({"ok": True})


@app.get("/api/settings/download-folder")
async def api_get_download_folder() -> JSONResponse:
    return JSONResponse(download_folder_settings())


@app.post("/api/settings/pick-folder")
async def api_pick_folder() -> JSONResponse:
    """Open the OS folder picker (macOS / Windows / Linux), then save like POST download-folder."""
    picked = await asyncio.to_thread(native_pick_folder)
    if not picked:
        raise HTTPException(status_code=400, detail="No folder selected (cancelled or dialog failed)")
    try:
        p = Path(picked).expanduser().resolve()
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}") from e
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Not an existing folder")
    if not os.access(p, os.W_OK):
        raise HTTPException(status_code=400, detail="Folder is not writable")
    try:
        DOWNLOAD_SETTINGS_PATH.write_text(
            json.dumps({"download_dir": str(p)}, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return JSONResponse(
        {
            "ok": True,
            "download_dir": str(p),
            "folder_ok": True,
            "resolved_path": str(p),
        }
    )


@app.post("/api/settings/download-folder")
async def api_set_download_folder(body: DownloadFolderBody) -> JSONResponse:
    raw = body.download_dir.strip()
    if not raw:
        try:
            DOWNLOAD_SETTINGS_PATH.write_text(
                json.dumps({"download_dir": ""}, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "download_dir": "", "folder_ok": False, "resolved_path": None})
    try:
        p = Path(raw).expanduser().resolve()
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}") from e
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not an existing folder")
    if not os.access(p, os.W_OK):
        raise HTTPException(status_code=400, detail="Folder is not writable")
    try:
        DOWNLOAD_SETTINGS_PATH.write_text(
            json.dumps({"download_dir": str(p)}, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return JSONResponse(
        {
            "ok": True,
            "download_dir": str(p),
            "folder_ok": True,
            "resolved_path": str(p),
        }
    )


@app.post("/api/playlist-info")
async def api_playlist_info(body: PlaylistInfoBody) -> JSONResponse:
    _cleanup_expired_sessions()
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")
    has_list = _youtube_list_param(url) is not None
    is_pl_page = "youtube.com/playlist" in url
    if not has_list and not is_pl_page:
        return JSONResponse(
            {
                "is_playlist": False,
                "playlist_title": None,
                "entries": [],
                "current_video_id": _youtube_video_id(url),
                "playlist_count": None,
                "entries_truncated": False,
            }
        )
    try:
        ensure_tools()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    data = await asyncio.to_thread(_run_ytdlp_playlist_flat, url, METADATA_TIMEOUT * 2)
    pl_title, entries = _parse_playlist_flat_entries(data)
    list_id = _youtube_list_param(url)
    if len(entries) == 0 and list_id:
        try:
            data = await asyncio.to_thread(
                _run_ytdlp_playlist_flat,
                _youtube_playlist_url_from_list_id(list_id),
                METADATA_TIMEOUT * 2,
            )
            pl_title, entries = _parse_playlist_flat_entries(data)
        except HTTPException:
            pass

    cur_vid = _youtube_video_id(url)
    current_index = None
    if cur_vid and entries:
        for e in entries:
            if e.get("id") == cur_vid:
                current_index = e["index"]
                break
    if current_index is None and entries:
        ip = _youtube_index_param(url)
        if ip is not None and 1 <= ip <= len(entries):
            current_index = ip

    playlist_count: Optional[int] = None
    pc_raw = data.get("playlist_count")
    if pc_raw is not None:
        try:
            playlist_count = int(pc_raw)
        except (ValueError, TypeError):
            playlist_count = None
    if playlist_count is None and entries:
        playlist_count = len(entries)

    entries_truncated = False
    if entries and len(entries) >= PLAYLIST_FLAT_MAX:
        entries_truncated = True
    elif playlist_count is not None and len(entries) < playlist_count:
        entries_truncated = True

    return JSONResponse(
        {
            "is_playlist": len(entries) > 0,
            "playlist_title": pl_title,
            "entries": entries,
            "current_video_id": cur_vid,
            "current_index": current_index,
            "playlist_count": playlist_count,
            "entries_truncated": entries_truncated,
        }
    )


@app.post("/api/metadata")
async def api_metadata(body: MetadataBody) -> JSONResponse:
    _cleanup_expired_sessions()
    if not _youtube_url_ok(body.url):
        raise HTTPException(status_code=400, detail="Invalid or unsupported YouTube URL")
    try:
        ensure_tools()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    info = await asyncio.to_thread(_run_ytdlp_json, body.url.strip(), METADATA_TIMEOUT)
    thumbs = info.get("thumbnails") or []
    thumb = info.get("thumbnail")
    if not thumb and thumbs:
        thumb = thumbs[-1].get("url")
    duration = info.get("duration")
    if duration is None:
        duration = 0.0
    return JSONResponse(
        {
            "title": info.get("title") or "Unknown",
            "duration_sec": float(duration),
            "thumbnail": thumb,
        }
    )


@app.post("/api/prepare")
async def api_prepare(body: PrepareBody) -> JSONResponse:
    _cleanup_expired_sessions()
    if not _youtube_url_ok(body.url):
        raise HTTPException(status_code=400, detail="Invalid or unsupported YouTube URL")
    fmt = body.format.strip().lower()
    if fmt not in ("mp3", "mp4", "m4a"):
        raise HTTPException(status_code=400, detail='format must be "mp3", "m4a", or "mp4"')
    mode = body.playlist_mode
    if mode == "items" and not (body.playlist_items and body.playlist_items.strip()):
        raise HTTPException(status_code=400, detail='playlist_items is required when playlist_mode is "items"')
    try:
        ensure_tools()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if body.previous_session_id:
        _destroy_session(body.previous_session_id)

    sid = uuid.uuid4().hex
    session_dir = TEMP_ROOT / sid
    url = body.url.strip()
    pl_timeout = min(DOWNLOAD_TIMEOUT * 6, 6 * 60 * 60)

    def work_single() -> Tuple[List[Path], List[str], str, float, Optional[str], Optional[str]]:
        info = _run_ytdlp_json(url, METADATA_TIMEOUT)
        path = _run_ytdlp_download(url, session_dir, fmt)
        title = info.get("title") or "Unknown"
        d = info.get("duration")
        dur = float(d) if d is not None else 0.0
        thumbs = info.get("thumbnails") or []
        th = info.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None)
        return [path], [title], title, dur, th, None

    def work_playlist(
        items_arg: Optional[str], header_title: str
    ) -> Tuple[List[Path], List[str], str, float, Optional[str], Optional[str]]:
        paths, pl_warn = _run_ytdlp_download_playlist(url, session_dir, fmt, items_arg, pl_timeout)
        titles = [p.stem for p in paths]
        display = header_title if len(paths) > 1 else titles[0]
        dur = _ffprobe_duration_seconds(paths[0]) if paths else 0.0
        thumb = None
        vid0 = _youtube_video_id(url)
        try:
            if not vid0:
                pdata = _run_ytdlp_playlist_flat(url, METADATA_TIMEOUT, playlist_end=1)
                _, ent = _parse_playlist_flat_entries(pdata)
                if ent:
                    vid0 = ent[0].get("id")
            if vid0:
                info0 = _run_ytdlp_json(f"https://www.youtube.com/watch?v={vid0}", METADATA_TIMEOUT)
                thumbs = info0.get("thumbnails") or []
                thumb = info0.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None)
        except HTTPException:
            pass
        return paths, titles, display, dur, thumb, pl_warn

    if mode == "single":

        def work() -> Tuple[List[Path], List[str], str, float, Optional[str], Optional[str]]:
            return work_single()

    elif mode == "all":

        def work() -> Tuple[List[Path], List[str], str, float, Optional[str], Optional[str]]:
            data = _run_ytdlp_playlist_flat(url, METADATA_TIMEOUT * 2, playlist_end=1)
            header = (
                (data.get("title") or data.get("playlist_title") or "").strip() or "Playlist"
            )
            return work_playlist(None, header)

    else:

        def work() -> Tuple[List[Path], List[str], str, float, Optional[str], Optional[str]]:
            return work_playlist(body.playlist_items.strip(), "Selection")

    paths, titles, display_title, duration_sec, thumbnail, prepare_warning = await asyncio.to_thread(work)

    skipped_playlist_indices: Optional[List[int]] = None
    if mode == "items" and body.playlist_items and body.playlist_items.strip():
        want = _expand_playlist_items_spec(body.playlist_items.strip())
        if want:
            got_idx = _playlist_output_indices_from_paths(paths)
            missed = [i for i in want if i not in got_idx]
            if missed:
                skipped_playlist_indices = missed
                suffix = f" Not downloaded — playlist #{', #'.join(str(x) for x in missed)}."
                if prepare_warning:
                    prepare_warning = prepare_warning.rstrip(".") + suffix
                else:
                    prepare_warning = "Some selected tracks could not be downloaded." + suffix

    _store_session(Session(
        id=sid,
        created=time.time(),
        full_path=paths[0],
        title=display_title,
        duration_sec=duration_sec,
        thumbnail=thumbnail,
        media_format=fmt,
        media_paths=list(paths),
        media_titles=list(titles),
    ))

    ext = paths[0].suffix.lstrip(".") or fmt
    files_out = [
        {
            "index": i,
            "title": titles[i],
            "filename_suggestion": _safe_filename_base(titles[i]) + paths[i].suffix,
        }
        for i in range(len(paths))
    ]
    return JSONResponse(
        {
            "session_id": sid,
            "title": display_title,
            "duration_sec": duration_sec,
            "thumbnail": thumbnail,
            "format": fmt,
            "filename_suggestion": _safe_filename_base(titles[0]) + f".{ext}",
            "file_count": len(paths),
            "files": files_out,
            "clips_enabled": len(paths) == 1 and fmt == "mp3",
            "prepare_warning": prepare_warning,
            "skipped_playlist_indices": skipped_playlist_indices,
        }
    )


@app.get("/api/session/{session_id}/full", response_model=None)
async def download_full(
    session_id: str,
    background_tasks: BackgroundTasks,
    delivery: Literal["browser", "copy_only"] = Query(
        "browser",
        description="browser = file download; copy_only = save to locked folder only (no save dialog)",
    ),
):
    _cleanup_expired_sessions()
    s = _get_session(session_id)
    if not s or not s.full_path.is_file():
        raise HTTPException(status_code=404, detail="Session or file not found")
    if len(s.media_paths) > 1:
        raise HTTPException(
            status_code=400,
            detail="Multiple tracks in this session — use each track’s download button.",
        )
    fname = _safe_filename_base(s.title) + s.full_path.suffix

    if delivery == "copy_only":
        info = download_folder_settings()
        if not info.get("folder_ok") or not info.get("resolved_path"):
            raise HTTPException(
                status_code=400,
                detail="No save folder configured. Choose folder or Save path first.",
            )
        dest_dir = Path(info["resolved_path"])
        safe_name = Path(fname).name
        dest = dest_dir / safe_name
        try:
            shutil.copy2(s.full_path, dest)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not copy to folder: {e}") from e
        return JSONResponse(
            {
                "ok": True,
                "filename": safe_name,
                "folder": str(dest_dir),
                "saved_path": str(dest),
            }
        )

    media = _media_type(s.media_format)
    background_tasks.add_task(_copy_to_saved_folder, s.full_path, fname)
    return FileResponse(
        path=s.full_path,
        media_type=media,
        filename=fname,
    )


@app.get("/api/session/{session_id}/part/{part_index}", response_model=None)
async def download_part(
    session_id: str,
    part_index: int,
    background_tasks: BackgroundTasks,
    delivery: Literal["browser", "copy_only"] = Query(
        "browser",
        description="browser = file download; copy_only = save to locked folder only",
    ),
):
    _cleanup_expired_sessions()
    s = _get_session(session_id)
    if not s or part_index < 0 or part_index >= len(s.media_paths):
        raise HTTPException(status_code=404, detail="Session or part not found")
    path = s.media_paths[part_index]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    title_part = s.media_titles[part_index] if part_index < len(s.media_titles) else s.title
    fname = _safe_filename_base(title_part) + path.suffix

    if delivery == "copy_only":
        info = download_folder_settings()
        if not info.get("folder_ok") or not info.get("resolved_path"):
            raise HTTPException(
                status_code=400,
                detail="No save folder configured. Choose folder or Save path first.",
            )
        dest_dir = Path(info["resolved_path"])
        safe_name = Path(fname).name
        dest = dest_dir / safe_name
        try:
            shutil.copy2(path, dest)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not copy to folder: {e}") from e
        return JSONResponse(
            {
                "ok": True,
                "filename": safe_name,
                "folder": str(dest_dir),
                "saved_path": str(dest),
            }
        )

    media = _media_type(s.media_format)
    background_tasks.add_task(_copy_to_saved_folder, path, fname)
    return FileResponse(
        path=path,
        media_type=media,
        filename=fname,
    )


@app.post("/api/session/{session_id}/clip")
async def create_clip(session_id: str, body: ClipBody) -> JSONResponse:
    _cleanup_expired_sessions()
    s = _get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s.media_format != "mp3":
        raise HTTPException(status_code=400, detail="Clips are only supported for MP3 sessions")
    if len(s.media_paths) != 1:
        raise HTTPException(
            status_code=400,
            detail="Clips only work for a single prepared file (not multi-track playlists).",
        )
    if not s.full_path.is_file():
        raise HTTPException(status_code=404, detail="Source audio missing")

    try:
        start_sec = parse_timestamp(body.start)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    end_sec: Optional[float] = None
    if body.end is not None and str(body.end).strip():
        try:
            end_sec = parse_timestamp(body.end)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    if body.duration_sec is not None and body.duration_sec > 0:
        duration = float(body.duration_sec)
    elif end_sec is not None:
        duration = end_sec - start_sec
    else:
        raise HTTPException(status_code=400, detail="Provide end time or duration (seconds)")

    if duration <= 0:
        raise HTTPException(status_code=400, detail="Clip duration must be positive")

    dur_limit = s.duration_sec or 0.0
    if dur_limit > 0:
        if start_sec < 0 or start_sec >= dur_limit:
            raise HTTPException(
                status_code=400,
                detail=f"Start must be within 0 and video duration ({dur_limit:.1f}s)",
            )
        if start_sec + duration > dur_limit + 0.25:
            raise HTTPException(
                status_code=400,
                detail="Clip extends past video duration",
            )

    clip_id = uuid.uuid4().hex
    clip_name = body.name.strip() if body.name and body.name.strip() else f"clip_{int(time.time())}"
    safe = _safe_filename_base(clip_name)
    out_path = s.full_path.parent / f"{clip_id}_{safe}.mp3"

    await asyncio.to_thread(_ffmpeg_trim_copy, s.full_path, out_path, start_sec, duration)
    s.clip_paths[clip_id] = out_path

    return JSONResponse(
        {
            "clip_id": clip_id,
            "download_url": f"/api/session/{session_id}/clip/{clip_id}/file",
            "filename_suggestion": f"{safe}.mp3",
        }
    )


def _delete_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _finalize_clip_to_folder_then_delete(src: Path, filename: str, clips_subdir: str) -> None:
    info = download_folder_settings()
    if info.get("folder_ok") and info.get("resolved_path"):
        dest_root = Path(info["resolved_path"])
        clips_dir = dest_root / clips_subdir
        try:
            clips_dir.mkdir(parents=True, exist_ok=True)
            dest = clips_dir / Path(filename).name
            shutil.copy2(src, dest)
        except OSError:
            pass
    _delete_path(src)


@app.get("/api/session/{session_id}/clip/{clip_id}/file", response_model=None)
async def download_clip(
    session_id: str,
    clip_id: str,
    background_tasks: BackgroundTasks,
    delivery: Literal["browser", "copy_only"] = Query(
        "browser",
        description="browser = file download; copy_only = locked folder only",
    ),
):
    _cleanup_expired_sessions()
    s = _get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    path = s.clip_paths.get(clip_id)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")

    fname = path.name
    if "_" in fname:
        rest = fname.split("_", 1)[1]
        fname = rest if rest.endswith(".mp3") else fname

    clips_subdir = _session_clips_subdir_name(s)

    if delivery == "copy_only":
        info = download_folder_settings()
        if not info.get("folder_ok") or not info.get("resolved_path"):
            raise HTTPException(
                status_code=400,
                detail="No save folder configured. Choose folder or Save path first.",
            )
        dest_root = Path(info["resolved_path"])
        clips_dir = dest_root / clips_subdir
        safe_name = Path(fname).name
        try:
            clips_dir.mkdir(parents=True, exist_ok=True)
            dest = clips_dir / safe_name
            shutil.copy2(path, dest)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not copy clip: {e}") from e
        s.clip_paths.pop(clip_id, None)
        _delete_path(path)
        return JSONResponse(
            {
                "ok": True,
                "filename": safe_name,
                "folder": str(clips_dir),
                "saved_path": str(dest),
            }
        )

    background_tasks.add_task(_finalize_clip_to_folder_then_delete, path, fname, clips_subdir)
    s.clip_paths.pop(clip_id, None)

    return FileResponse(
        path=path,
        media_type="audio/mpeg",
        filename=fname,
    )


@app.get("/api/updates/check")
async def api_updates_check() -> JSONResponse:
    """Return installed vs latest yt-dlp version from PyPI, and whether yt-dlp-ejs is installed."""
    venv_py = _project_venv_python()
    py = str(venv_py) if venv_py else sys.executable
    versions: dict[str, str] = {}
    try:
        r = subprocess.run(
            [py, "-m", "pip", "show", "yt-dlp", "yt-dlp-ejs"],
            capture_output=True, text=True, timeout=15,
        )
        name: Optional[str] = None
        for line in r.stdout.splitlines():
            key, _, value = line.partition(":")
            if key == "Name":
                name = re.sub(r"[-_.]+", "-", value.strip()).lower()
            elif key == "Version" and name:
                versions[name] = value.strip()
    except Exception:
        pass
    installed = versions.get("yt-dlp")
    # Without yt-dlp-ejs, yt-dlp can't solve YouTube's JS challenges and formats go missing.
    ejs_installed = "yt-dlp-ejs" in versions

    latest: Optional[str] = None
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/yt-dlp/json",
            headers={"User-Agent": "tube-grab/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            latest = data["info"]["version"]
    except Exception:
        pass

    up_to_date = bool(installed and latest and installed == latest and ejs_installed)
    return JSONResponse(
        {"installed": installed, "latest": latest, "up_to_date": up_to_date, "ejs_installed": ejs_installed}
    )


@app.post("/api/updates/run")
async def api_updates_run() -> JSONResponse:
    """Upgrade yt-dlp and its default extras (including yt-dlp-ejs) in the project venv via pip."""
    venv_py = _project_venv_python()
    py = str(venv_py) if venv_py else sys.executable

    def _do_upgrade() -> subprocess.CompletedProcess:
        return subprocess.run(
            [py, "-m", "pip", "install", "-U", YTDLP_PIP_REQUIREMENT],
            capture_output=True, text=True, timeout=180,
        )

    try:
        r = await asyncio.to_thread(_do_upgrade)
        ok = r.returncode == 0
        output = (r.stdout + r.stderr).strip()
        if ok:
            # Reset cmd cache so the app picks up the new binary
            global _ytdlp_cmd_cache, _ytdlp_probe_failed
            _ytdlp_cmd_cache = None
            _ytdlp_probe_failed = False
        return JSONResponse({"ok": ok, "output": output})
    except Exception as e:
        return JSONResponse({"ok": False, "output": str(e)}, status_code=500)


# Optional: mount static for favicon etc.
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    # uvicorn imports `main` from the process cwd; lock cwd to this project.
    os.chdir(APP_DIR)
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
