#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h:h}"
APP="$ROOT/dist/Codex Memory Harbor.app"
CONTENTS="$APP/Contents"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
xcrun swiftc "$ROOT/macos/CodexMemoryHarbor.swift" -o "$CONTENTS/MacOS/CodexMemoryHarbor" -framework Cocoa -framework WebKit
cp "$ROOT/skills/codex-memory-harbor/assets/icon-large.svg" "$CONTENTS/Resources/icon.svg"
ICON_SOURCE="$ROOT/skills/codex-memory-harbor/assets/memory-harbor-logo-v2-1024.png"
ICONSET="$ROOT/dist/MemoryHarbor.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$ICON_SOURCE" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  retina=$((size * 2))
  sips -z "$retina" "$retina" "$ICON_SOURCE" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$CONTENTS/Resources/MemoryHarbor.icns"
rm -rf "$ICONSET"
/usr/libexec/PlistBuddy -c 'Clear dict' "$CONTENTS/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c 'Add :CFBundleName string Codex Memory Harbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleDisplayName string Codex Memory Harbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string com.alexsolar.codex-memory-harbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleVersion string 4' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleShortVersionString string 0.2.0-beta.1' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleExecutable string CodexMemoryHarbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string MemoryHarbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :LSMinimumSystemVersion string 13.0' "$CONTENTS/Info.plist"
codesign --force --deep --sign - "$APP"
echo "$APP"
