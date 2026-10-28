# 0005. Run Python through a symlink inside Tube Grab.app

Date: 2026-10-27

## Status

Accepted

## Context

The desktop window runs inside the python.org framework's own `Python.app`, so macOS showed "Python" in the menu bar, Dock and app switcher. Changing `CFBundleName` or the process name from inside Python renamed the app in LaunchServices, but the menu bar still said "Python".

## Decision

We decided that the `Tube Grab.app` launcher (`Contents/MacOS/tubegrab`) creates a symlink, `Contents/MacOS/Tube Grab`, pointing at the framework interpreter. It then runs that symlink with `__PYVENV_LAUNCHER__` set to the project's venv Python, the same mechanism the framework's own stub uses. macOS then treats the process as `Tube Grab.app`, with its name, bundle ID and icon. The symlink is machine-specific, so the launcher makes it and `.gitignore` excludes it.

## Consequences

**Positive:**
- The menu bar, Dock and app switcher say "Tube Grab" with the app's icon. The owner confirmed this by eye.

**Negative:**
- It depends on a python.org framework build at `<base_prefix>/Resources/Python.app`. With other Python builds, the launcher falls back to running the venv Python and the name shows "Python" again.
- `__PYVENV_LAUNCHER__` is an undocumented internal variable of the framework stub and could change in a future Python.

**Neutral:**
- Launching with `python desktop.py` or `tube-grab.command` doesn't get the new name.

## Alternatives Considered

### Alternative: Copy the interpreter binary into the bundle

macOS code signing kills the copied binary (SIGKILL). Rejected.

### Alternative: py2app or PyInstaller

A real, self-contained app. Rejected as a much bigger build and release process for a personal tool.

---

*Linked from:* PR #1 (commit dd5474f), `Tube Grab.app/Contents/MacOS/tubegrab`, `desktop.py` (`_set_macos_app_name`)
