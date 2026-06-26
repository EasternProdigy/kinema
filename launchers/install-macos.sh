#!/usr/bin/env bash
# Build a real "Kinema.app" and add it to your Mac (opt-in — only run this if you
# want the app icon). By default it opens Kinema as a normal browser tab; pass a
# mode to change that:
#   bash launchers/install-macos.sh            # tab   (default)
#   bash launchers/install-macos.sh app        # dedicated Kinema window
#   bash launchers/install-macos.sh kiosk      # fullscreen cinema mode
set -e
MODE="${1:-tab}"
case "$MODE" in
  tab|app|kiosk) ;;
  *) echo "Usage: install-macos.sh [tab|app|kiosk]"; exit 1 ;;
esac

FLAG=""
[ "$MODE" = "app" ]   && FLAG="--app"
[ "$MODE" = "kiosk" ] && FLAG="--kiosk"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Install into /Applications if we can write there, otherwise ~/Applications.
APPS="/Applications"; [ -w "$APPS" ] || APPS="$HOME/Applications"
mkdir -p "$APPS"
APP="$APPS/Kinema.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# The bundle's executable just hands off to the shared launcher.
cat > "$APP/Contents/MacOS/Kinema" <<EOF
#!/bin/bash
exec "$DIR/launchers/kinema.sh" $FLAG
EOF
chmod +x "$APP/Contents/MacOS/Kinema"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Kinema</string>
  <key>CFBundleDisplayName</key><string>Kinema</string>
  <key>CFBundleIdentifier</key><string>app.mezi.kinema</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundleExecutable</key><string>Kinema</string>
  <key>CFBundleIconFile</key><string>kinema</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>10.12</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

# Build an .icns from the shipped PNG (best effort; the app still works without).
PNG="$DIR/launchers/kinema.png"
if [ -f "$PNG" ] && command -v sips >/dev/null 2>&1; then
  SET="$(mktemp -d)/kinema.iconset"; mkdir -p "$SET"
  for s in 16 32 128 256 512; do
    sips -z "$s"      "$s"      "$PNG" --out "$SET/icon_${s}x${s}.png"     >/dev/null 2>&1 || true
    sips -z $((s*2))  $((s*2))  "$PNG" --out "$SET/icon_${s}x${s}@2x.png"  >/dev/null 2>&1 || true
  done
  iconutil -c icns "$SET" -o "$APP/Contents/Resources/kinema.icns" >/dev/null 2>&1 \
    || sips -s format icns "$PNG" --out "$APP/Contents/Resources/kinema.icns" >/dev/null 2>&1 || true
fi

# Nudge LaunchServices/Finder to register the app and its icon.
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" >/dev/null 2>&1 || true

# Add a Desktop alias too.
ln -sfn "$APP" "$HOME/Desktop/Kinema.app" 2>/dev/null || true

echo "Installed: $APP   (mode: $MODE)"
echo "Find 'Kinema' in Launchpad / Applications, or use the Desktop alias."
