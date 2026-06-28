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

## Fonts

Kadmu bundles two open-source typefaces (in `src/web/fonts/`), used under the
**SIL Open Font License 1.1**:

- **Poppins** — © The Indian Type Foundry & contributors. <https://fonts.google.com/specimen/Poppins>
- **IBM Plex Mono** — © IBM Corp. <https://github.com/IBM/plex>

The SIL OFL permits bundling and redistribution. Brand colors and the "mezi"
visual language are property of Pentarosa Co.
