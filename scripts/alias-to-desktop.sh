#!/bin/bash
# Creates a Finder alias to Tube Grab.app on your Desktop (macOS).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/Tube Grab.app"
[[ -d "$APP" ]] || { echo "Missing $APP"; exit 1; }
osascript -e "tell application \"Finder\" to make alias file to (POSIX file \"$APP\") at (path to desktop folder)"
echo "Alias created on Desktop (points to Tube Grab in your clone)."
