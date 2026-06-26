#!/usr/bin/env bash
# Add a Kinema icon to your Linux desktop & app menu (opt-in — only run this if
# you want the icon). By default the icon opens Kinema as a normal browser tab;
# pass a mode to change that:
#   bash launchers/install-linux.sh            # tab   (default)
#   bash launchers/install-linux.sh app        # dedicated Kinema window
#   bash launchers/install-linux.sh kiosk      # fullscreen cinema mode
set -e
MODE="${1:-tab}"
case "$MODE" in
  tab|app|kiosk) ;;
  *) echo "Usage: install-linux.sh [tab|app|kiosk]"; exit 1 ;;
esac

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"

FLAG=""
[ "$MODE" = "app" ]   && FLAG=" --app"
[ "$MODE" = "kiosk" ] && FLAG=" --kiosk"

ICON="$DIR/launchers/kinema.png"
[ -f "$ICON" ] || ICON="$DIR/src/web/favicon.svg"

DESKTOP="$APPS/kinema.desktop"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Kinema
GenericName=Personal cinema
Comment=Watch your own video library in a browser
Exec=bash "$DIR/launchers/kinema.sh"$FLAG
Icon=$ICON
Terminal=false
Categories=AudioVideo;Player;
StartupNotify=false
EOF

chmod +x "$DIR/launchers/kinema.sh" "$DESKTOP" 2>/dev/null || true
update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "Installed: $DESKTOP   (mode: $MODE)"
echo "Kinema should now appear in your applications menu (search 'Kinema')."

# Also drop a double-clickable icon on the Desktop, if there is one.
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP_DIR" ]; then
  cp "$DESKTOP" "$DESKTOP_DIR/Kinema.desktop"
  chmod +x "$DESKTOP_DIR/Kinema.desktop"
  gio set "$DESKTOP_DIR/Kinema.desktop" metadata::trusted true 2>/dev/null || true
  # KDE Plasma: mark the file as trusted so double-click runs it without a prompt
  kwriteconfig5 --file "$DESKTOP_DIR/Kinema.desktop" --group "Desktop Entry" --key "X-KDE-AuthorizeAction" "shell_access" 2>/dev/null || true
  echo "Added a Kinema icon to your Desktop: $DESKTOP_DIR/Kinema.desktop"
fi
