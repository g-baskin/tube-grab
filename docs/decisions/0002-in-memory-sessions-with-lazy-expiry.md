# 0002. Keep sessions in memory with a 2-hour lazy expiry

Date: 2026-04-03

## Status

Accepted

## Context

A prepare creates files under `temp/<session-id>/`, which the UI then downloads, copies or trims. Tube Grab has one user on one machine, so it needs to know which files belong to which request, without adding a database.

## Decision

We decided to keep sessions in a Python dict guarded by `SESSION_LOCK` (`main.py`). Sessions expire after `SESSION_TTL_SEC` (2 hours). Expiry runs only when a session endpoint is called, and then deletes the session's folder. A new prepare can also drop the previous session (`previous_session_id`).

## Consequences

**Positive:**
- No database or background job, and nothing to migrate.

**Negative:**
- Restarting the server loses every session. Files already in `temp/` stay there until removed by hand.
- With no timer, an idle server leaves expired files on disk until the next request.
- Only one server process can serve a session, so there's no scaling out.

**Neutral:**
- Clips are deleted after their first download, independent of the session expiry.

## Alternatives Considered

### Alternative: SQLite or a session table

It survives restarts. Rejected as more moving parts than a single-user local tool needs.

### Alternative: A background cleanup timer

It removes expired files on time. Rejected so far because lazy cleanup is good enough locally. Revisit it if `temp/` growth becomes a problem.

---

*Linked from:* commit 1489975, `main.py` (`SESSION_TTL_SEC`, `SESSION_LOCK`, `_cleanup_expired_sessions`)
