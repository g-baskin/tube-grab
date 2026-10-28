<!-- gg:init:start -->
# Tube Grab

Single-user local tool: FastAPI (`main.py`) shells out to yt-dlp/ffmpeg to download YouTube videos or playlists as MP3/M4A/MP4 and cut MP3 clips. The UI is one page (`static/index.html`, inline JS), shown in a browser or a pywebview window (`desktop.py`).

## Parts
- `main.py`: everything server-side. Tool discovery, metadata and playlists, prepare/download, in-memory sessions, clips, save-folder setting, yt-dlp self-update (`/api/updates/*`).
- `desktop.py`: starts uvicorn as a child on 127.0.0.1:8749 (`TUBE_GRAB_PORT`, no reload), polls `/api/health`, opens the window, kills the child on close.
- `Tube Grab.app/Contents/MacOS/tubegrab`: bash launcher. The repo root is the folder **containing** the `.app`, so never move or copy the bundle (use `scripts/alias-to-desktop.sh`). It prepends `/opt/homebrew/bin:/usr/local/bin` to PATH because Finder apps don't get the shell PATH.
- `temp/<session-id>/` (downloads) and `download_settings.json` (save folder) are local state and gitignored.

## Gotchas
- **yt-dlp resolution order is PATH → current interpreter → `.venv`**, cached for the process, *including a failed lookup*. A Homebrew `yt-dlp` beats the venv one, and then the in-app updater (which upgrades only the venv) silently changes nothing. After installing yt-dlp, restart, or clear `_ytdlp_cmd_cache`/`_ytdlp_probe_failed` as `/api/updates/run` does.
- **YouTube needs `yt-dlp[default]`, not plain `yt-dlp`.** The extra brings `yt-dlp-ejs`, which (with a JS runtime; Deno is installed here) solves YouTube's JS challenges. Without it formats go missing, with no clear error. Any pip install or upgrade must use `"yt-dlp[default]"`.
- **Missing tools don't stop startup.** `lifespan` turns `ensure_tools()` errors (yt-dlp, ffmpeg, ffprobe) into a printed warning, so check `/api/health` instead of assuming.
- **pywebview/WKWebView ignores `<a href>` downloads.** Every file download in the UI must go through `triggerGetDownload` (fetch → blob → `<a download>`), which reads the filename from `Content-Disposition`, so keep `FileResponse(filename=...)`.
- **Format names `mp3|m4a|mp4` are duplicated across files and must stay in sync:** `/api/prepare` validation, both yt-dlp download paths, `_media_type`, the UI radios, and the `loadFormat` localStorage whitelist (an unlisted value is silently dropped on reload). Clips work only for a single-file MP3 session (`clips_enabled`).
- **Sessions are in-memory only** (lost on restart). They expire after 2 h, checked lazily on requests (no timer), and the folder is deleted then. A clip file is deleted after its first download.
- **Every browser GET of `/full` or `/part` also copies the file into the save folder** as a background task, and copy errors are swallowed. The UI uses `?delivery=copy_only` when a folder is locked.
- **No auth and `allow_origins=["*"]`**, while endpoints write files and run pip. Keep binding to 127.0.0.1.
- `/api/updates/check` runs blocking `subprocess.run`/`urlopen` inside `async def`. Use `asyncio.to_thread` (as everywhere else) rather than copying that pattern.
- **macOS app name:** the window process runs inside Python.framework's `Python.app`, so the menu bar says "Python". Setting `CFBundleName` or `setProcessName_` in-process changes LaunchServices' name but **not** the menu bar. What works is running the interpreter through a symlink inside `Tube Grab.app/Contents/MacOS/` with `__PYVENV_LAUNCHER__=<venv python>`. A *copied* interpreter is SIGKILLed by code signing.

## Branches
- **Never delete `dev`, `qa` or `main`** (owner's rule). GitHub rulesets enforce it: "Protect main and qa" (PR required, no force-push or deletion) and "Keep dev" (no deletion).
- Flow: `feature/<slug>` → PR into `dev` → PR `dev`→`qa` → PR `qa`→`main`; never push straight to `qa`/`main` (GitHub rejects it).
- "Automatically delete head branches" is on, so merging a `dev`→`qa` PR tries to delete `dev`; the "Keep dev" rule is what stops that. Don't remove that ruleset or turn deletion protection off.

## Running and restarting
- `python main.py` = dev server on :8000 with reload. The desktop paths (`Tube Grab.app`, `tube-grab.command`, `desktop.py`) use :8749 and never reload, so a running window serves old code until relaunched.
- **Relaunch check:** the uvicorn child can outlive `desktop.py` (orphaned to launchd, still on :8749), and SIGTERM to `desktop.py` can be slow or ignored while the Cocoa loop runs. A new launch then fails to bind, but its health poll succeeds against the **stale** server, so old code keeps running with no error. Before relaunching, confirm `lsof -iTCP:8749 -sTCP:LISTEN` is empty, and stop leftovers by exact PID.
- To test changes without touching the user's running app, serve the worktree on another port (`uvicorn main:app --port 8750` from the repo root, or `TUBE_GRAB_PORT=8751`).
- Window screenshots and System Events UI scripting are blocked on this Mac (no Screen Recording/Accessibility permission). Use a headless browser on `http://127.0.0.1:<port>`, or ask the user to look.

## Checks
No tests, CI, pyproject or lint config exist, and pytest isn't installed (the parent folder's `pytest` default doesn't apply). Useful checks: `.venv/bin/python -m py_compile main.py desktop.py`, `shellcheck` on `scripts/*.sh` and the `tubegrab` launcher (its pre-existing SC1112 curly-quote warning is known), and `node --check` on each inline `<script>` block extracted from `static/index.html`.
<!-- gg:init:end -->
