# Roadmap / TODO

Netflix-style features we've discussed but haven't built yet. Each should respect the
project constraints: Python **standard library only**, **vanilla** HTML/CSS/JS, everything
behind the existing security gate, and brand values from [BRAND.md](BRAND.md).

## Player

- [ ] **Scrub-preview thumbnails** — a thumbnail filmstrip on the seek bar while hovering
      (sprite/`.vtt` thumbnail track generated with ffmpeg, cached like other artifacts).
      We currently show only a time bubble.
- [ ] **Skip Intro / Skip Recap** — a "Skip" button over a known intro range. Needs
      per-episode markers (manual config, or chapter/silence/black-frame detection).
- [ ] **Audio-track switching** — pick among multiple audio streams in a container
      (expose via ffprobe; select on remux/transcode).

## Library / browse

- [ ] **Hero / billboard banner** — a featured title at the top of the home view.
- [ ] **Sort & filter controls** — by name / date added / recently watched, etc.
- [ ] **"Recently added" row** — surface newly-added files on the home view.

## Notes

- Subtitles today are **sidecar-only** (`.srt`/`.vtt` next to the video, `.srt`→`.vtt`
  on the fly). Extracting embedded subtitle tracks from `.mkv` is intentionally out of scope
  for now (would mean per-play ffmpeg subtitle muxing).
- Search matches **filenames** (no metadata DB).
