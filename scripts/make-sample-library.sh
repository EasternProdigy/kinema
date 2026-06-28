#!/usr/bin/env bash
# Generates a small, 100% royalty-free sample library using ffmpeg test patterns.
# Used for the public demo (and for trying Kadmu without your own files).
#   bash scripts/make-sample-library.sh [output-dir]
set -e
OUT="${1:-sample-library}"
mkdir -p "$OUT/Kadmu Demo Show/Season 1" "$OUT/Demo Movies"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required to generate sample clips."; exit 1
fi

# Pick an available H.264 encoder (browser-playable).
if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q ' libx264'; then
  VC="libx264"
elif ffmpeg -hide_banner -encoders 2>/dev/null | grep -q ' libopenh264'; then
  VC="libopenh264"
else
  echo "No H.264 encoder (libx264/libopenh264) found in ffmpeg."; exit 1
fi
echo "Using video encoder: $VC"

mk() {  # $1=video filter  $2=duration  $3=output
  ffmpeg -loglevel error -y \
    -f lavfi -i "$1" \
    -f lavfi -i "sine=frequency=320:duration=$2" \
    -t "$2" -c:v "$VC" -b:v 800k -pix_fmt yuv420p -c:a aac "$3"
  echo "  created: $3"
}

mk "testsrc=size=854x480:rate=24"     12 "$OUT/Kadmu Demo Show/Season 1/Episode 1 - Pilot.mp4"
mk "testsrc2=size=854x480:rate=24"    10 "$OUT/Kadmu Demo Show/Season 1/Episode 2 - The Reveal.mp4"
mk "mandelbrot=size=854x480:rate=24"  15 "$OUT/Demo Movies/Fractal Voyage.mp4"
mk "smptebars=size=854x480:rate=24"    8 "$OUT/Demo Movies/Color Bars Classic.mp4"

echo "Sample library ready at: $OUT"
echo "Try it read-only:  python3 src/server.py \"$OUT\" --read-only"
