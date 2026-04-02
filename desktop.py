#!/usr/bin/env python3
"""
Tube Grab — desktop shell: starts uvicorn (no --reload) and opens a native window.

Usage (from repo root, venv active or use .venv/bin/python):
  pip install -r requirements-desktop.txt
  python desktop.py

Optional: TUBE_GRAB_PORT=8749 (default) to avoid clashing with a dev server on 8000.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def _pick_port() -> int:
    """Default 8749 so it won’t fight a dev server on 8000; override with TUBE_GRAB_PORT."""
    raw = os.environ.get("TUBE_GRAB_PORT", "").strip()
    if raw.isdigit():
        return int(raw)
    return 8749


def _wait_ready(port: int, timeout_sec: float = 90.0) -> bool:
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.25)
    return False


def main() -> None:
    os.chdir(APP_DIR)
    port = _pick_port()

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        # No --reload: fewer moving parts, better for leaving open all day.
    ]
    # Inherit stdout/stderr so if you launch from Terminal you still see uvicorn logs.
    proc = subprocess.Popen(cmd, cwd=str(APP_DIR))

    def cleanup() -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda *_: (cleanup(), sys.exit(130)))
    signal.signal(signal.SIGTERM, lambda *_: (cleanup(), sys.exit(143)))

    if not _wait_ready(port):
        cleanup()
        print("Tube Grab: server did not become ready in time.", file=sys.stderr)
        sys.exit(1)

    try:
        import webview
    except ImportError:
        cleanup()
        print(
            "Install desktop deps: pip install -r requirements-desktop.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    webview.create_window(
        "Tube Grab",
        f"http://127.0.0.1:{port}",
        width=1180,
        height=820,
        min_size=(800, 600),
    )
    webview.start(debug=False)
    cleanup()


if __name__ == "__main__":
    main()
