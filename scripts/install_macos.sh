#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
SKILL_DEST="$HOME/.codex/skills/codex-memory-harbor"
APP_DEST="$HOME/Applications/Memory Harbor.app"
NEW_LABEL="com.alexsolar.memory-harbor"
OLD_LABEL="com.alexsolar.codex-memory-harbor"
NEW_PLIST="$HOME/Library/LaunchAgents/$NEW_LABEL.plist"
OLD_PLIST="$HOME/Library/LaunchAgents/$OLD_LABEL.plist"
LAUNCH_DOMAIN="gui/$(/usr/bin/id -u)"
STAMP="$(/bin/date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$HOME/Library/Application Support/Memory Harbor/Migration Backups"
TRASH_DIR="$HOME/.Trash"

LOGIN_ITEM=false
if [[ "${1:-}" == "--login-item" || -f "$NEW_PLIST" || -f "$OLD_PLIST" ]]; then
  LOGIN_ITEM=true
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--login-item]" >&2
  exit 2
fi

mkdir -p "$HOME/.codex/skills" "$HOME/Applications" "$HOME/Library/LaunchAgents" "$BACKUP_DIR" "$TRASH_DIR"

# Stop both the renamed app and the legacy copy before replacing either bundle.
/bin/launchctl bootout "$LAUNCH_DOMAIN/$NEW_LABEL" >/dev/null 2>&1 || true
/bin/launchctl bootout "$LAUNCH_DOMAIN/$OLD_LABEL" >/dev/null 2>&1 || true
/usr/bin/pkill -TERM -x MemoryHarborDashboard >/dev/null 2>&1 || true
/usr/bin/pkill -TERM -x CodexMemoryHarborDashboard >/dev/null 2>&1 || true
/usr/bin/pkill -TERM -x MemoryHarbor >/dev/null 2>&1 || true
/usr/bin/pkill -TERM -x CodexMemoryHarbor >/dev/null 2>&1 || true

# Older helpers could leave their Python child behind after an abrupt exit.
while read -r SERVER_PID SERVER_COMMAND; do
  if [[ "$SERVER_COMMAND" == *"$SKILL_DEST/scripts/harbor.py serve"* ]]; then
    /bin/kill -TERM "$SERVER_PID" >/dev/null 2>&1 || true
  fi
done < <(/bin/ps -axo pid=,command=)

ditto "$ROOT/skills/codex-memory-harbor" "$SKILL_DEST"
"$ROOT/scripts/build_macos_app.sh" >/dev/null

STAGING_APP="$HOME/Applications/.Memory Harbor.app.installing"
rm -rf "$STAGING_APP"
ditto "$ROOT/dist/Memory Harbor.app" "$STAGING_APP"
codesign --verify --deep --strict "$STAGING_APP"

if [[ -d "$APP_DEST" ]]; then
  mv "$APP_DEST" "$TRASH_DIR/Memory Harbor.app.previous-$STAMP"
fi
mv "$STAGING_APP" "$APP_DEST"

# Retire every known pre-rename app so Launch Services and TCC see one owner.
for LEGACY_APP in \
  "/Applications/Codex Memory Harbor.app" \
  "$HOME/Applications/Codex Memory Harbor.app" \
  "/Applications/Memory Harbor.app"; do
  if [[ -d "$LEGACY_APP" && "$LEGACY_APP" != "$APP_DEST" ]]; then
    mv "$LEGACY_APP" "$TRASH_DIR/${LEGACY_APP:t:r}.app.migrated-$STAMP"
  fi
done

if [[ -L "$HOME/Desktop/Memory Harbor.app" ]]; then
  ln -sfn "$APP_DEST" "$HOME/Desktop/Memory Harbor.app"
elif [[ ! -e "$HOME/Desktop/Memory Harbor.app" ]]; then
  ln -s "$APP_DEST" "$HOME/Desktop/Memory Harbor.app"
fi
if [[ -L "$HOME/Desktop/Codex Memory Harbor.app" ]]; then
  mv "$HOME/Desktop/Codex Memory Harbor.app" "$TRASH_DIR/Codex Memory Harbor.app.link.migrated-$STAMP"
fi

if [[ -f "$OLD_PLIST" ]]; then
  mv "$OLD_PLIST" "$BACKUP_DIR/$OLD_LABEL.plist.migrated-$STAMP"
fi

if $LOGIN_ITEM; then
  /usr/libexec/PlistBuddy -c 'Clear dict' "$NEW_PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :Label string $NEW_LABEL" "$NEW_PLIST"
  /usr/libexec/PlistBuddy -c 'Add :ProgramArguments array' "$NEW_PLIST"
  /usr/libexec/PlistBuddy -c 'Add :ProgramArguments:0 string /usr/bin/open' "$NEW_PLIST"
  /usr/libexec/PlistBuddy -c "Add :ProgramArguments:1 string $APP_DEST" "$NEW_PLIST"
  /usr/libexec/PlistBuddy -c 'Add :RunAtLoad bool true' "$NEW_PLIST"
  /bin/launchctl bootstrap "$LAUNCH_DOMAIN" "$NEW_PLIST"
else
  open "$APP_DEST"
fi

echo "Installed: $APP_DEST"
