#!/usr/bin/env bash
# Adds Kinema to your Linux applications menu so you can launch it like any app.
# Run once:  bash launchers/install-linux.sh
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"

DESKTOP="$APPS/kinema.desktop"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Kinema
GenericName=Personal cinema
Comment=Watch your own video library in a browser tab
Exec=bash "$DIR/launchers/kinema.sh"
Icon=$DIR/web/favicon.svg
Terminal=false
Categories=AudioVideo;Player;
StartupNotify=false
EOF

chmod +x "$DIR/launchers/kinema.sh" "$DESKTOP" 2>/dev/null || true
update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "Installed: $DESKTOP"
echo "Kinema should now appear in your applications menu (search 'Kinema')."
