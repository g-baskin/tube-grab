# Tube Grab glossary

One name per idea. The **Term** column is the name to use in new UI text and docs. "Also called" lists the names already in the code or API. Those stay as they are, because renaming endpoints, JSON fields or the settings file would break existing setups.

| Term | Meaning | Also called (where) |
|---|---|---|
| **Track** | One downloaded audio or video file in a session. A single video gives one track; a playlist gives one per entry. | `part` (`GET /api/session/{id}/part/{n}`), `file` (`file_count`, `files[]` in `/api/prepare`), `media_paths` (`Session` in `main.py`) |
| **Session** | One finished prepare: its tracks under `temp/<session-id>/`, kept in memory for up to 2 hours. See [ADR 0002](docs/decisions/0002-in-memory-sessions-with-lazy-expiry.md). | `session_id`, `sid` |
| **Prepare** | Running yt-dlp (and ffprobe) on the server to create a session's tracks. The UI button for it is **Download Full**. | `POST /api/prepare`, `work()` |
| **New grab** | Clearing the current URL and session to start again. | `newGrab()` |
| **Save folder** | The folder you choose so tracks and clips are copied there automatically, with no browser save dialog. While one is set, the UI shows **Locked in**. | `download_dir` (`download_settings.json`), `/api/settings/download-folder`, `download_folder_settings()`, `_copy_to_saved_folder()` |
| **Delivery** | How a track or clip reaches you: `browser` (the file comes back, and is also copied to the save folder if one is set) or `copy_only` (only copied to the save folder). | `delivery` query parameter |
| **Format** | What a prepare produces: `mp3`, `m4a` (audio, no conversion) or `mp4` (video). | `format` (API), `media_format` (`Session`), `fmt` |
| **Clip** | A trimmed MP3 cut from a single-track MP3 session with ffmpeg stream copy. Deleted after its first download. | `clip_id`, `clips_enabled` |
| **Playlist scope** | Which videos a playlist URL downloads: **This video only**, **Selected tracks** or **Entire playlist**. | `playlist_mode` = `single` / `items` / `all`, `playlist_items`, `plScope` (UI) |
| **Entry** | One video listed in a playlist before download (title, duration, id). | `entries` (`/api/playlist-info`) |
| **Background video** | Muted random YouTube videos playing behind the UI (arrives with PR #1). | `bgVideo`, `tubegrab:bgVideo` |

Decisions that are hard to undo are recorded in [docs/decisions](docs/decisions/README.md).
