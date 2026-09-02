#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h:h}"
SKILL_DEST="$HOME/.codex/skills/codex-memory-harbor"
APP_DEST="$HOME/Applications/Codex Memory Harbor.app"
mkdir -p "$HOME/.codex/skills" "$HOME/Applications"
ditto "$ROOT/skills/codex-memory-harbor" "$SKILL_DEST"
"$ROOT/scripts/build_macos_app.sh" >/dev/null
ditto "$ROOT/dist/Codex Memory Harbor.app" "$APP_DEST"
if [[ ! -e "$HOME/Desktop/Codex Memory Harbor.app" ]]; then
  ln -s "$APP_DEST" "$HOME/Desktop/Codex Memory Harbor.app"
fi
if [[ "${1:-}" == "--login-item" ]]; then
  PLIST="$HOME/Library/LaunchAgents/com.alexsolar.codex-memory-harbor.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  /usr/libexec/PlistBuddy -c 'Clear dict' "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c 'Add :Label string com.alexsolar.codex-memory-harbor' "$PLIST"
  /usr/libexec/PlistBuddy -c 'Add :ProgramArguments array' "$PLIST"
  /usr/libexec/PlistBuddy -c 'Add :ProgramArguments:0 string /usr/bin/open' "$PLIST"
  /usr/libexec/PlistBuddy -c 'Add :ProgramArguments:1 string -a' "$PLIST"
  /usr/libexec/PlistBuddy -c 'Add :ProgramArguments:2 string Codex Memory Harbor' "$PLIST"
  /usr/libexec/PlistBuddy -c 'Add :RunAtLoad bool true' "$PLIST"
fi
open "$APP_DEST"
echo "Installed: $APP_DEST"
