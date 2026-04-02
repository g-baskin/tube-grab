#!/bin/bash
# Double-click in Finder (macOS) or run from Terminal to open Tube Grab in a desktop window.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
if [ -x "$DIR/.venv/bin/python" ]; then
  exec "$DIR/.venv/bin/python" desktop.py
else
  exec python3 desktop.py
fi
