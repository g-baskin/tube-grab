# Tube Grab

Private, local web app: pull **YouTube** audio (**MP3**) or video (**MP4**) with **yt-dlp**, optional **playlists** (this video only / selected tracks / full list), fast **MP3 clips** with **ffmpeg** stream copy (`-c copy`). Single-page UI + FastAPI; files land in `./temp` until you save or the session expires (~2 hours).

**Use responsibly:** personal/archival use; respect YouTube’s terms and copyright.

## Clone

```bash
git clone https://github.com/g-baskin/tube-grab.git
cd tube-grab
```

## Prerequisites

Install **yt-dlp** and **ffmpeg** and ensure both are on your `PATH`.

### macOS (Homebrew)

```bash
brew install yt-dlp ffmpeg
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y ffmpeg
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp
```

### Windows (Chocolatey)

```powershell
choco install yt-dlp ffmpeg -y
```

You can also install **yt-dlp** via pip inside the venv (see below); **ffmpeg** must still be installed separately.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` includes **yt-dlp**. Resolution order in the app: `yt-dlp` on **PATH** → `python -m yt_dlp` on the **same interpreter as uvicorn** → **`./.venv/bin/python -m yt_dlp`** if that venv can import `yt_dlp`. **Restart the server** after `pip install` if downloads still fail.

## Run

**Recommended (venv activated):**

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

**Without activating venv:**

```bash
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

**Alternative:**

```bash
.venv/bin/python main.py
```

Open **http://127.0.0.1:8000**

If you see `Could not import module "main"`, run uvicorn from the **repository root** (this folder). If you see **Missing yt-dlp**, use **`.venv/bin/python`** as above.

## Desktop app (native window, no dev reload)

The dev command uses **`--reload`**, which watches files and restarts often—fine for coding, not ideal for “leave it open all day.”

**`desktop.py`** starts **uvicorn without `--reload`** (more stable) and opens a **native window** (WebKit on macOS, Edge WebView2 on Windows) pointed at the local server. Closing the window stops the server.

```bash
pip install -r requirements-desktop.txt
python desktop.py
```

- Default URL is **http://127.0.0.1:8749** (so it won’t collide with a dev server on **8000**). Override with `TUBE_GRAB_PORT=8000` if you want.

### macOS: **Tube Grab.app** (Dock icon + double-click)

The repo includes **`Tube Grab.app`** in the **project root** (next to `desktop.py`). It has a custom icon and runs `desktop.py` using your project **`.venv`** if present.

1. **`pip install -r requirements-desktop.txt`** once (same as above).
2. **Double-click `Tube Grab.app`** in Finder, or drag it to the **Dock**.

**Icon on your Desktop (recommended):** don’t copy only the `.app` to the Desktop — it must stay **inside** the repo so it can find `desktop.py`. Instead:

- **Option A:** In Finder, **right-click `Tube Grab.app` → Make Alias**, drag the **alias** to the Desktop, or  
- **Option B:** Run **`./scripts/alias-to-desktop.sh`** from the repo (creates that alias for you).

First launch, if macOS blocks it: **right-click the app → Open** once, or clear quarantine:  
`xattr -dr com.apple.quarantine "Tube Grab.app"`

**Also available:** **`tube-grab.command`** — double-click opens a Terminal window with server logs.

### Windows

Use **`python desktop.py`** (or a shortcut to that command). There is no `.app` bundle on Windows; use **PyInstaller** later if you want a `.exe` with an icon.

**Even more “app-like”:** you can wrap `desktop.py` with **[PyInstaller](https://pyinstaller.org/)** into a single binary (large). For most people, **`Tube Grab.app`** or `desktop.py` is enough.

**If the backend ever dies** while the window is still open, restart the app. A future improvement would be auto-restart on health-check failure.

## Workflow

1. Paste a `youtube.com/watch?v=…`, `youtu.be/…`, or `youtube.com/playlist?…` URL (metadata loads after a short debounce).
2. If the URL is a **playlist** (`list=` on watch URLs or a `/playlist?list=` page), choose **This video only**, **Selected tracks**, or **Entire playlist**. Then pick **MP3** or **MP4**.
3. Tap **Download Full** to run yt-dlp (can take a long time for big playlists). That step prepares files on the server. **Multiple tracks:** with a **locked save folder**, tracks are **copied there automatically** when prepare finishes; without it, click **each ↓** so the browser saves every file.
4. **Single MP3 file only:** set **Start**, **End** or **Duration**, optional clip name → **Generate & Download Clip** (ffmpeg stream copy; frame-aligned, not sample-perfect).

## Large playlists

- **Entire playlist** is one long yt-dlp run (sequential). The UI bar stays indeterminate; keep the tab open.
- The picker lists up to **200** titles; **Entire playlist** still downloads the **full** list via yt-dlp.
- The app uses **`-N 4`** (concurrent fragments) for faster segments; tune **`YTDLP_CONCURRENT_FRAGMENTS`** in `main.py` if you like.
- Keep **yt-dlp** updated (`pip install -U yt-dlp`). Unavailable entries are skipped with **`--ignore-errors`**.

## API (for scripts)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Tool probe: `ok`, `ytdlp`, `ffmpeg`, etc. |
| `GET` | `/api/settings/download-folder` | Persisted save folder |
| `POST` | `/api/settings/pick-folder` | Native OS folder picker (macOS/Linux/Windows) |
| `POST` | `/api/settings/download-folder` | Set or clear `download_dir` |
| `POST` | `/api/metadata` | `{ "url" }` → title, duration, thumbnail |
| `POST` | `/api/playlist-info` | Playlist metadata, entries (capped), `playlist_count`, `entries_truncated` |
| `POST` | `/api/prepare` | Download prepare; supports `playlist_mode` / `playlist_items`; may return `prepare_warning`, `skipped_playlist_indices` |
| `DELETE` | `/api/session/{id}` | Drop session + temp files |
| `GET` | `/api/session/{id}/full` | Single-track download (`delivery=browser` or `copy_only`) |
| `GET` | `/api/session/{id}/part/{n}` | Per-track download when `file_count` > 1 |
| `POST` | `/api/session/{id}/clip` | Create MP3 clip (single-track sessions) |
| `GET` | `/api/session/{id}/clip/{clip_id}/file` | Download clip; with save folder → `{title}_clips/` subfolder |

## Using the API from another app (e.g. soundtrack → your product)

Tube Grab is a **local** tool: it **prepares** files under `./temp` and serves them over HTTP. It does **not** include “upload this file to S3 / your API” — that stays in **your** app, which should **download the bytes** from Tube Grab, then **upload** them wherever you need (storage bucket, your backend, CMS, etc.).

**Typical flow (server-side, recommended):**

1. `POST /api/prepare` with `url`, `format` (`mp3` | `mp4`), and optional `playlist_mode` / `playlist_items` (same JSON as the UI). Waits until yt-dlp finishes (use a long HTTP timeout, e.g. 30–60+ minutes for big playlists).
2. Read `session_id`, `file_count`, and `files[]` from the JSON response.
3. For **one** file: `GET /api/session/{session_id}/full` → response body is the audio/video bytes (`Content-Disposition` has a filename).
4. For **many** tracks: `GET /api/session/{session_id}/part/0`, `/part/1`, … up to `file_count - 1`.
5. Your code uploads those bytes to **your** service (multipart form, presigned URL, tRPC mutation, etc.).
6. `DELETE /api/session/{session_id}` when finished to free disk (optional; sessions also expire after ~2 hours).

**Port:** `desktop.py` defaults to **8749**; dev uvicorn often uses **8000**. Use the same host/port your running instance logs on startup.

**Security:** Treat Tube Grab as **trusted local only** (`127.0.0.1`). Do not expose it to the public internet without putting your own auth/reverse-proxy in front. CORS is permissive for the bundled UI; for integrations, prefer calling Tube Grab from **your backend**, not from the browser, so you don’t ship a public “download anything from YouTube” endpoint.

**Minimal Python example (single track):**

```python
import requests

BASE = "http://127.0.0.1:8749"  # or 8000 if using uvicorn dev
payload = {"url": "https://www.youtube.com/watch?v=VIDEO_ID", "format": "mp3", "playlist_mode": "single"}
r = requests.post(f"{BASE}/api/prepare", json=payload, timeout=3600)
r.raise_for_status()
data = r.json()
sid = data["session_id"]
audio = requests.get(f"{BASE}/api/session/{sid}/full", timeout=600)
audio.raise_for_status()
# e.g. upload audio.content to your storage or POST to your API
requests.delete(f"{BASE}/api/session/{sid}", timeout=30)
```

That’s enough to treat Tube Grab as a **“YouTube → bytes”** sidecar while your app owns uploads, metadata, and user auth.

## Notes

- **`download_settings.json`** (save folder path) is **gitignored** — not committed.
- **`temp/`** is gitignored — session payloads are local only.
- Clips require **one** prepared **MP3** file (not multi-track sessions).
- For personal use only; respect platform terms and rights holders.

## License

Private repository; no license file included unless you add one. Use and share at your own discretion.
