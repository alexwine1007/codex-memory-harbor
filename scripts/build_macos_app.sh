#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h:h}"
APP="$ROOT/dist/Memory Harbor.app"
CONTENTS="$APP/Contents"
rm -rf "$APP"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
xcrun swiftc "$ROOT/macos/CodexMemoryHarbor.swift" -o "$CONTENTS/MacOS/MemoryHarbor" -framework Cocoa
HELPER="$CONTENTS/Helpers/Memory Harbor Dashboard.app"
mkdir -p "$HELPER/Contents/MacOS"
xcrun swiftc "$ROOT/macos/CodexMemoryHarborDashboard.swift" -o "$HELPER/Contents/MacOS/MemoryHarborDashboard" -framework Cocoa -framework WebKit
/usr/libexec/PlistBuddy -c 'Clear dict' "$HELPER/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c 'Add :CFBundleName string Memory Harbor Dashboard' "$HELPER/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleDisplayName string Memory Harbor Dashboard' "$HELPER/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string com.alexsolar.memory-harbor.dashboard' "$HELPER/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleVersion string 12' "$HELPER/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleShortVersionString string 0.4.3-beta.1' "$HELPER/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleExecutable string MemoryHarborDashboard' "$HELPER/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :LSMinimumSystemVersion string 13.0' "$HELPER/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :NSRemovableVolumesUsageDescription string Memory Harbor needs access to your selected archive drive to verify and restore docked task history.' "$HELPER/Contents/Info.plist"
cp "$ROOT/skills/codex-memory-harbor/assets/icon-large.svg" "$CONTENTS/Resources/icon.svg"
ICON_SOURCE="$ROOT/skills/codex-memory-harbor/assets/memory-harbor-logo-v4-1024.png"
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
/usr/libexec/PlistBuddy -c 'Add :CFBundleName string Memory Harbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleDisplayName string Memory Harbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string com.alexsolar.memory-harbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleVersion string 12' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleShortVersionString string 0.4.3-beta.1' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleExecutable string MemoryHarbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string MemoryHarbor' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :LSMinimumSystemVersion string 13.0' "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :NSRemovableVolumesUsageDescription string Memory Harbor needs access to your selected archive drive to verify and restore docked task history.' "$CONTENTS/Info.plist"

SIGN_IDENTITY="$("$ROOT/scripts/ensure_codesign_identity.sh")"
codesign --force --sign "$SIGN_IDENTITY" "$HELPER"
codesign --force --sign "$SIGN_IDENTITY" "$APP"
codesign --verify --deep --strict "$APP"
echo "$APP"
