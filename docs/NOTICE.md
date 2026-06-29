# Third-party notices

Kadmu itself is licensed under the [MIT License](../LICENSE), © 2026 Pentarosa Co.

## FFmpeg

The prebuilt release bundles (from the [Releases](../../../releases) page) include
**ffmpeg** and **ffprobe** binaries so thumbnails work without a separate install.
These binaries are part of the **FFmpeg** project and are **not** covered by Kadmu's
MIT license — they are distributed under their own terms (LGPL/GPL, depending on the
build):

- Project & source: <https://ffmpeg.org/> and <https://git.ffmpeg.org/ffmpeg.git>
- FFmpeg licensing: <https://ffmpeg.org/legal.html>

Static builds bundled by our release pipeline are sourced from:

- Linux — John Van Sickle static builds: <https://johnvansickle.com/ffmpeg/>
- Windows — BtbN FFmpeg-Builds: <https://github.com/BtbN/FFmpeg-Builds>
- macOS — evermeet.cx: <https://evermeet.cx/ffmpeg/>

If you run Kadmu from source (not the bundles), it simply uses whatever `ffmpeg`
is already on your `PATH` (or the one pointed to by `KADMU_FFMPEG` /
`KADMU_FFPROBE`), and no FFmpeg binary is distributed with the source.

FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project.

## hls.js

Kadmu bundles **hls.js** (`src/web/js/hls.min.js`) to play HLS adaptive-bitrate
streams in browsers that lack native HLS (Firefox, Chrome). It is loaded on demand
only when the player's "Auto" quality is selected. hls.js is **not** covered by
Kadmu's MIT license — it is distributed under the **Apache License 2.0**:

- Project & source: <https://github.com/video-dev/hls.js>
- License: <https://github.com/video-dev/hls.js/blob/master/LICENSE>

© the hls.js project authors and contributors.

## Google Cast SDK (opt-in only)

When — and **only when** — Kadmu is started with `--cast` (`KADMU_CAST=1`), the browser
loads Google's **Cast Sender SDK** from Google's `gstatic.com` CDN to enable casting to a
Chromecast. This is the single exception to Kadmu's "no third-party scripts / no phone-home"
default: it is **off by default**, the script is **not bundled** (it's fetched from Google),
and the app-shell Content-Security-Policy is relaxed for `gstatic.com` solely while `--cast`
is enabled. It is **not** covered by Kadmu's MIT license and is subject to Google's terms.

- SDK: <https://www.gstatic.com/cv/js/sender/v1/cast_sender.js>
- Google Cast & terms: <https://developers.google.com/cast> · <https://developers.google.com/cast/docs/terms>

Casting (and DLNA) keep video on your LAN — the Chromecast pulls the bytes directly from
your node, so Kadmu's cloud still never touches them. If you'd rather not involve Google's
SDK at all, leave `--cast` off and use **DLNA** (`--dlna`) instead.

## YouTube trailer embeds (click-triggered)

When a title is matched to TMDB, its page shows a **Trailer** button that plays the trailer
in an in-app lightbox via a **YouTube** embed, using the privacy-enhanced
`youtube-nocookie.com` domain. The app-shell Content-Security-Policy permits this iframe
(`frame-src`), but **nothing loads until you click Trailer** (which only appears with the
optional, default-off TMDB layer enabled), and closing the lightbox removes the iframe and
ends contact with YouTube. The embedded player and its content are Google/YouTube's, governed
by their terms — not Kadmu's MIT license.

- YouTube terms: <https://www.youtube.com/t/terms>

## Fonts

Kadmu bundles two open-source typefaces (in `src/web/fonts/`), used under the
**SIL Open Font License 1.1**:

- **Poppins** — © The Indian Type Foundry & contributors. <https://fonts.google.com/specimen/Poppins>
- **IBM Plex Mono** — © IBM Corp. <https://github.com/IBM/plex>

The SIL OFL permits bundling and redistribution. Brand colors and the "mezi"
visual language are property of Pentarosa Co.
