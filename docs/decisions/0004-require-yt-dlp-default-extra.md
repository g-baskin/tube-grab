# 0004. Require `yt-dlp[default]` for YouTube

Date: 2026-10-27

## Status

Accepted

## Context

Since yt-dlp 2025.11.12, YouTube downloads depend on the `yt-dlp-ejs` package (plus a JavaScript runtime such as Deno) to solve YouTube's JavaScript challenges. Plain `pip install yt-dlp` doesn't install it. Without it, formats go missing and downloads fail, with no clear error.

## Decision

We decided to require `yt-dlp[default]>=2025.11.12` in `requirements.txt`. The in-app updater installs `YTDLP_PIP_REQUIREMENT = "yt-dlp[default]"`. `/api/updates/check` reports the install as out of date while `yt-dlp-ejs` is missing.

## Consequences

**Positive:**
- A normal setup or in-app update installs everything YouTube needs, apart from the JavaScript runtime.

**Negative:**
- Eight extra packages are installed.
- The JavaScript runtime (Deno) still has to be installed separately, and nothing in the app checks for it.
- A yt-dlp found earlier on PATH (for example Homebrew's) is used first, and the updater doesn't touch it.

**Neutral:**
- Every pip command that installs yt-dlp for this project must use the `[default]` extra.

## Alternatives Considered

### Alternative: Fetch the solver at runtime (`--remote-components ejs:github`)

No extra package to install. Rejected because it downloads code on every cold start and depends on GitHub being reachable.

### Alternative: Plain `yt-dlp`

Smaller install, but YouTube breaks.

---

*Linked from:* commit c858714, `requirements.txt`, `main.py` (`YTDLP_PIP_REQUIREMENT`, `/api/updates/*`)
