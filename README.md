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

## Notes

- **`download_settings.json`** (save folder path) is **gitignored** — not committed.
- **`temp/`** is gitignored — session payloads are local only.
- Clips require **one** prepared **MP3** file (not multi-track sessions).
- For personal use only; respect platform terms and rights holders.

## License

Private repository; no license file included unless you add one. Use and share at your own discretion.
