# Kadmu — Brand Guidelines

The single source of truth for how Kadmu looks and sounds. Mirrors the Pentarosa /
mezi brand kit so the family feels of-a-piece. The visual deck is
[brand/kadmu-brand-guidelines.html](brand/kadmu-brand-guidelines.html) (open it in a
browser); the tokens below are exactly what ships in [../src/web/style.css](../src/web/style.css).

> **Rule of thumb:** any UI or marketing change must come *out of this file*. If a value
> isn't here, it doesn't belong in the product. Update this doc and `style.css` together.

**Tagline:** *Your cinema, in a tab.*

---

## 01 — Logo · the mark

A **play triangle** (press play on your own library) inside a **warm gradient tile** — the
same mark used as the favicon and the top-bar brand tile.

- Mark path: `M26 21.5v21l18-10.5z` on a `0 0 64 64` viewBox.
- Tile: rounded square (`rx 16` of 64 ≈ 25%), filled with the brand gradient.
- **Wordmark:** lowercase `kadmu`, ink on light / all-white on dark. The wordmark stays
  **monochrome** — color lives only in the tile.
- **Clear space:** ≥ 12% of the tile width on all sides.

| Variant | Tile | Triangle |
|---------|------|----------|
| Primary | gradient | white |
| Reversed | white | orange `#EE6722` |
| Ink | white | ink `#211915` |
| Knockout | slate `#1E2A38` | white |
| Flat | orange `#EE6722` | white |

**Don't:** recolor the wordmark, add a second accent color, outline the triangle, stretch
the tile, or set the wordmark in any face other than Poppins.

---

## 02 — Color

Orange is the signal color; a warm-neutral ink scale carries everything else.

| Token | Hex | Role |
|-------|-----|------|
| **Kadmu Orange** | `#EE6722` | signal / accent (RGB 238 103 34 · PMS ~165C) |
| **Ember** | `#F5832F` | gradient start |
| **Burnt** | `#EA5C20` | gradient end |

Brand gradient: `linear-gradient(135deg, #F5832F, #EA5C20)`.

**Warm ink scale:** `900 #211915` · `700 #3d332c` · `500 #6f655d` · `300 #b8afa7` ·
`100 #e7e0d9` · **Paper** `#f7f4f1`.

**Supporting & semantic:** Sand `#fbe9dd` · Slate `#1e2a38` · Success `#2fa969` ·
Error `#e0524d`.

App chrome (light, warm): `--bg: Paper` · `--surface: #fff` · `--surface-2: #fbf8f5` ·
`--line: #ece4db` · `--text: ink-900` · `--muted: ink-500` · `--accent: orange`.

**Dark mode** keeps the warm hue but inverts the ink scale's lightness, so the same
tokens carry both themes. Orange stays the only accent; the player stage is dark in
both. Auto-follows the OS preference; a top-bar toggle cycles auto → light → dark.

| Token | Dark value | Role |
|-------|-----------|------|
| **ink-900** | `#f3ede7` | text (warm near-white) |
| **ink-700** | `#d9d0c8` | strong text |
| **ink-500** | `#a59c93` | muted |
| **ink-300** | `#786e66` | faint / placeholder |
| **ink-100** | `#352b24` | hairlines / subtle fills |
| **Paper / `--bg`** | `#161210` | warm near-black canvas |
| **`--surface`** | `#1e1813` | raised surface |
| **`--surface-2`** | `#251e18` | inset surface |
| **`--line`** | `#34291f` | borders |
| **Sand** | `#2a201a` | dark warm tile (behind folder/section glyphs) |

Dark chrome (warm): `--bg #161210` · `--surface #1e1813` · `--surface-2 #251e18` ·
`--line #34291f` · `--text ink-900` · `--muted ink-500` · `--accent orange`.

---

## 03 — Typography

One geometric sans everywhere; mono for figures.

- **Poppins** — product, marketing, docs. Weights 400 / 500 / 600 / 700.
- **IBM Plex Mono** — 400 / 500, for timecodes, durations, counts and other figures.
- Both are **bundled offline** as woff2 in [../src/web/fonts/](../src/web/fonts/) and served
  from `/fonts/*.woff2` — never link to a CDN.

Type scale: **Display** 56/700 · **H1** 40/700 · **H2** 28/600 · **Body** 16/400.

```css
--font: 'Poppins', system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
--mono: 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace;
```

---

## 04 — Shape & surface

Kadmu is **boxy and calm** — boxy over blobby, flat over glassy.

- `--radius: 4px`, `--radius-sm: 2px`. Tiles/cards stay tight; only the brand tile is round.
- Soft shadows only: `--shadow: 0 1px 2px rgba(33,25,21,.05)`,
  `--shadow-lg: 0 10px 30px rgba(33,25,21,.22)`. **No `backdrop-filter`, no glassmorphism.**
- Thumbnails sit on dark film-slate (`#20262e`); the play affordance is a **solid-orange
  square** button, not a circle.

---

## 05 — Voice & tone

Calm, plain-spoken, on the viewer's side. It's your stuff on your machine — never hypey,
never a streaming-service pitch.

1. **Clear over clever** — say what the button does; the useful thing first.
2. **Calm, not flashy** — no countdowns, no "premium experience," just the video.
3. **Human and direct** — talk like the friend who set up your media server.

**We say:** "Point Kadmu at a folder. Press play." · "Your files stay on your machine." ·
"Pop it out with Picture-in-Picture."

**We don't:** "Leverage our next-gen streaming platform." · "Sign in to unlock your
entertainment journey." · "Buffering your premium experience…"

Lowercase the wordmark (`kadmu`) in running text. Mark it as **Kadmu — by Pentarosa Co.**
on first/marketing mention.

---

## 06 — Brand in use

- **Favicon / app tile:** the gradient tile + white play triangle ([../src/web/favicon.svg](../src/web/favicon.svg)).
- **OG / social banner:** 1200 × 630, gradient background, white `kadmu` wordmark + tagline.
- **Contact in collateral:** `opensource@mezi.app` · `github.com/EasternProdigy/kadmu`.
  Never surface a personal name, email, or IP — see the privacy note in the repo's
  contribution/commit conventions.
