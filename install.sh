#!/usr/bin/env bash
# Kinema one-line installer for Linux & macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/EasternProdigy/kinema/main/install.sh | bash
#
# Downloads the latest release for your OS (ffmpeg bundled — nothing else to
# install) and launches it. If no release binary exists yet, it falls back to
# running from source with python3.
#
# Env overrides: KINEMA_REPO, KINEMA_HOME (install dir), KINEMA_BIN (PATH symlink dir).
set -euo pipefail

REPO="${KINEMA_REPO:-EasternProdigy/kinema}"
DEST="${KINEMA_HOME:-$HOME/.kinema-app}"
BIN_DIR="${KINEMA_BIN:-$HOME/.local/bin}"

cyan()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m%s\033[0m\n' "$*" >&2; }
die()   { printf '\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }

have curl || die "curl is required. Install curl and re-run."
have tar  || die "tar is required. Install tar and re-run."

case "$(uname -s)" in
  Linux)  ASSET="kinema-linux.tar.gz" ;;
  Darwin) ASSET="kinema-macos.tar.gz" ;;
  *) die "Unsupported OS. On Windows use install.ps1, or grab a build from https://github.com/$REPO/releases" ;;
esac

RUN=""

install_binary() {  # $1 = download URL
  cyan "Downloading $ASSET ..."
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  curl -fL --progress-bar "$1" -o "$tmp/kinema.tgz"
  rm -rf "$DEST"; mkdir -p "$DEST"
  tar -xzf "$tmp/kinema.tgz" -C "$DEST"
  chmod +x "$DEST/kinema" 2>/dev/null || true
  mkdir -p "$BIN_DIR"
  ln -sf "$DEST/kinema" "$BIN_DIR/kinema"
  green "Installed to $DEST"
  RUN="$DEST/kinema"
}

install_source() {
  warn "No release binary found — falling back to the source version."
  have python3 || die "Python 3 is required for the source install: https://www.python.org/downloads/"
  cyan "Downloading source ..."
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" -o "$tmp/src.tgz"
  rm -rf "$DEST"; mkdir -p "$DEST"
  tar -xzf "$tmp/src.tgz" -C "$DEST" --strip-components=1
  green "Installed source to $DEST"
  have ffmpeg || warn "(Tip: install ffmpeg, or set KINEMA_FFMPEG, to get thumbnails.)"
  RUN="python3 $DEST/src/server.py"
}

cyan "Kinema installer — finding the latest release of $REPO ..."
URL="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
        | grep -o "https://[^\"]*/$ASSET" | head -n1 || true)"

if [ -n "${URL:-}" ]; then install_binary "$URL"; else install_source; fi

green ""
green "✅ Kinema is installed."
case ":$PATH:" in
  *":$BIN_DIR:"*) [ -n "${URL:-}" ] && green "Start it any time with:  kinema" ;;
  *)              [ -n "${URL:-}" ] && green "Start it with:  $BIN_DIR/kinema   (add $BIN_DIR to your PATH to just type 'kinema')" ;;
esac
cyan "Starting Kinema now ..."
exec $RUN
