#!/usr/bin/env bash
# Kadmu one-line installer for Linux & macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/EasternProdigy/kadmu/main/install.sh | bash
#
# Downloads the latest release for your OS (ffmpeg bundled — nothing else to
# install) and launches it. If no release binary exists yet, it falls back to
# running from source with python3.
#
# Env overrides: KADMU_REPO, KADMU_HOME (install dir), KADMU_BIN (PATH symlink dir).
set -euo pipefail

REPO="${KADMU_REPO:-EasternProdigy/kadmu}"
DEST="${KADMU_HOME:-$HOME/.kadmu-app}"
BIN_DIR="${KADMU_BIN:-$HOME/.local/bin}"

cyan()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m%s\033[0m\n' "$*" >&2; }
die()   { printf '\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }

have curl || die "curl is required. Install curl and re-run."
have tar  || die "tar is required. Install tar and re-run."

case "$(uname -s)" in
  Linux)  ASSET="kadmu-linux.tar.gz" ;;
  Darwin) ASSET="kadmu-macos.tar.gz" ;;
  *) die "Unsupported OS. On Windows use install.ps1, or grab a build from https://github.com/$REPO/releases" ;;
esac

RUN=""

install_binary() {  # $1 = download URL
  cyan "Downloading $ASSET ..."
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  curl -fL --progress-bar "$1" -o "$tmp/kadmu.tgz"
  rm -rf "$DEST"; mkdir -p "$DEST"
  tar -xzf "$tmp/kadmu.tgz" -C "$DEST"
  chmod +x "$DEST/kadmu" 2>/dev/null || true
  mkdir -p "$BIN_DIR"
  ln -sf "$DEST/kadmu" "$BIN_DIR/kadmu"
  green "Installed to $DEST"
  RUN="$DEST/kadmu"
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
  have ffmpeg || warn "(Tip: install ffmpeg, or set KADMU_FFMPEG, to get thumbnails.)"
  RUN="python3 $DEST/src/server.py"
}

cyan "Kadmu installer — finding the latest release of $REPO ..."
URL="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
        | grep -o "https://[^\"]*/$ASSET" | head -n1 || true)"

if [ -n "${URL:-}" ]; then install_binary "$URL"; else install_source; fi

green ""
green "✅ Kadmu is installed."
case ":$PATH:" in
  *":$BIN_DIR:"*) [ -n "${URL:-}" ] && green "Start it any time with:  kadmu" ;;
  *)              [ -n "${URL:-}" ] && green "Start it with:  $BIN_DIR/kadmu   (add $BIN_DIR to your PATH to just type 'kadmu')" ;;
esac
cyan "Starting Kadmu now ..."
exec $RUN
