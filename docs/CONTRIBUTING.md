# Contributing to Kadmu

Thanks for your interest! Kadmu aims to stay **small, dependency-free, and easy to run**.
Please keep that spirit in mind for contributions.

## Principles

- **Backend = Python standard library only.** No third-party runtime dependencies.
- **Frontend = vanilla HTML/CSS/JS.** No build step, no framework.
- **ffmpeg/ffprobe are optional.** The app must still work (minus thumbnails) without them.
- **Security first.** Anything that touches the filesystem must stay inside the configured
  library roots and respect read-only mode. See [SECURITY.md](SECURITY.md).

## Dev setup

```bash
git clone https://github.com/EasternProdigy/kadmu.git
cd kadmu
python3 src/server.py ~/Videos    # run it  (or: ./scripts/run.sh)
```

There's no compile step — edit `src/web/*` and refresh the browser tab. For auto-restart
while hacking on the backend, use `./scripts/dev.sh` (it reloads when `src/server.py` changes).

## Before opening a PR

- `python3 -m py_compile src/server.py` — no syntax errors.
- `node --check src/web/app.js` (or any linter) — no JS syntax errors.
- Manually test: browse, play, resume, PiP, and (if relevant) `--lan`, `--password`,
  `--read-only`.
- Keep the diff focused and the code style consistent with what's there.

## Reporting bugs / ideas

Open a GitHub issue with steps to reproduce, your OS, and your browser. For security
issues, follow [SECURITY.md](SECURITY.md) instead of filing a public issue.

## License

By contributing you agree your contributions are licensed under the project's
[MIT License](../LICENSE).
