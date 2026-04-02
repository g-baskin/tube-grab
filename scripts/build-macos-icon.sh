#!/bin/bash
# Rebuild AppIcon.icns from branding/icon-source-1024.png (macOS only).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/branding/icon-source-1024.png"
OUT="$REPO/Tube Grab.app/Contents/Resources/AppIcon.icns"
IS="$REPO/.iconbuild.iconset"
rm -rf "$IS"
mkdir -p "$IS"
[[ -f "$SRC" ]] || { echo "Missing $SRC"; exit 1; }
sips -z 16 16 "$SRC" --out "$IS/icon_16x16.png" >/dev/null
sips -z 32 32 "$SRC" --out "$IS/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$SRC" --out "$IS/icon_32x32.png" >/dev/null
sips -z 64 64 "$SRC" --out "$IS/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$SRC" --out "$IS/icon_128x128.png" >/dev/null
sips -z 256 256 "$SRC" --out "$IS/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$SRC" --out "$IS/icon_256x256.png" >/dev/null
sips -z 512 512 "$SRC" --out "$IS/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$SRC" --out "$IS/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$SRC" --out "$IS/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$IS" -o "$OUT"
rm -rf "$IS"
echo "Wrote $OUT"
