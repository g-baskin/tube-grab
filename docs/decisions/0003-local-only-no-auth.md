# 0003. Run local-only on 127.0.0.1 with no login

Date: 2026-04-02

## Status

Accepted

## Context

Tube Grab is a personal tool. Its endpoints run yt-dlp, write files to disk, copy into a chosen folder and can run `pip install`. Adding login would add setup and friction for a single user.

## Decision

We decided to bind the server only to 127.0.0.1 (`desktop.py` and `main.py`) and to have no authentication. CORS allows every origin (`allow_origins=["*"]`), so the bundled page works however it's opened.

## Consequences

**Positive:**
- Zero setup: open the app and use it.

**Negative:**
- Any web page open in your browser can send requests to the local server, because CORS is open and there's no login. That includes starting downloads, changing the save folder, or running the yt-dlp update.
- Exposing it beyond localhost (a reverse proxy, port forwarding or `--host 0.0.0.0`) would hand those powers to anyone who can reach it.

**Neutral:**
- Integrations should call Tube Grab from your own backend, not from a public browser page (README, "Using the API from another app").

## Alternatives Considered

### Alternative: A login or per-launch token

It closes the drive-by-page hole. Not done yet. It's the first thing to add if Tube Grab is ever shared beyond one machine.

### Alternative: Restricting CORS to the app's own origin

A smaller step that blocks other sites' scripts from reading responses. Not yet adopted.

---

*Linked from:* `desktop.py` (`--host 127.0.0.1`), `main.py` (`CORSMiddleware`)
