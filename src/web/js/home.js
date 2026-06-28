"use strict";
/* home.js — the Netflix-style home surface shown at the library root: a hero
   (resume what you were watching, or a recently-added pick) and a "Recently
   added" rail. Built entirely from LOCAL data (the background index + your
   resume history) — no metadata service, no outbound calls. Also wires the
   storyboard-driven preview-on-hover used by every video card.
   Part of the Kadmu frontend; classic script sharing the global scope. */

async function renderHome() {
  const heroSec = $("#homeHero"), recentSec = $("#recentSection"), rail = $("#recentRail");
  if (!heroSec) return;
  let home = null;
  try { home = await api("/api/home"); } catch {}
  if (home && home.hero) renderHero(home.hero);
  else heroSec.classList.add("hidden");

  const recent = (home && home.recent) || [];
  if (recent.length && recentSec && rail) {
    recentSec.classList.remove("hidden");
    rail.innerHTML = "";
    for (const v of recent) rail.appendChild(videoCard(v));
  } else recentSec && recentSec.classList.add("hidden");
}

function renderHero(h) {
  const sec = $("#homeHero");
  if (!sec) return;
  sec.classList.remove("hidden");
  const resume = !!(h.position && h.duration && h.position < h.duration * 0.97 && h.position > 5);
  const pct = resume ? Math.min(100, (h.position / h.duration) * 100) : 0;
  const ctx = (typeof ctxLabel === "function") ? ctxLabel(h.path) : "";
  sec.innerHTML =
    `<div class="hero-backdrop"><img alt="" /></div>
     <div class="hero-scrim"></div>
     <div class="hero-content">
       <div class="hero-eyebrow">${h.reason === "resume" ? "Continue watching" : "Recently added"}</div>
       <h1 class="hero-title">${escapeHtml(dispName(h))}</h1>
       <div class="hero-sub">${escapeHtml([ctx, h.duration ? fmtTime(h.duration) : ""].filter(Boolean).join(" · "))}</div>
       ${pct ? `<div class="hero-prog"><i style="width:${pct}%"></i></div>` : ""}
       <div class="hero-actions">
         <button class="btn primary hero-play"><span data-icon="play"></span> ${resume ? "Resume" : "Play"}</button>
         <button class="btn ghost hero-open">Open folder</button>
       </div>
     </div>`;
  const bd = $(".hero-backdrop", sec), img = $(".hero-backdrop img", sec);
  img.onerror = () => bd && bd.classList.add("noimg");
  img.src = `/api/thumb?path=${enc(h.path)}`;
  applyIcons(sec);
  $(".hero-play", sec).onclick = () => openPlayer(h);
  $(".hero-open", sec).onclick = () => loadLibrary(parentDir(h.path));
}

/* ---------- preview-on-hover (storyboard frames cycled in the card) ---------- */
function attachHoverPreview(card, v) {
  if (!state.session || !state.session.ffmpeg || !v.playable) return;
  const thumb = card.querySelector(".thumb");
  if (!thumb) return;
  let timer = null, cycle = null, loaded = false;

  card.addEventListener("mouseenter", () => {
    timer = setTimeout(async () => {
      try {
        const info = await api(`/api/storyboard?path=${enc(v.path)}`);
        if (!info || !info.ok || !info.count) return;
        let ov = thumb.querySelector(".hover-prev");
        if (!ov) { ov = el("div", "hover-prev"); thumb.appendChild(ov); }
        const url = `/api/storyboard.jpg?path=${enc(v.path)}`;
        const im = new Image();
        im.onload = () => {
          if (!card.matches(":hover")) return;             // moved on while loading
          ov.style.backgroundImage = `url("${url}")`;
          ov.style.backgroundSize = `${info.cols * 100}% ${info.rows * 100}%`;
          ov.classList.add("on");
          loaded = true;
          let frame = Math.floor(info.count * 0.12);
          const show = () => {
            const col = frame % info.cols, row = Math.floor(frame / info.cols);
            ov.style.backgroundPosition =
              `${(col / Math.max(1, info.cols - 1)) * 100}% ${(row / Math.max(1, info.rows - 1)) * 100}%`;
            frame = (frame + 1) % info.count;
          };
          show();
          cycle = setInterval(show, 750);
        };
        im.src = url;
      } catch {}
    }, 450);
  });
  card.addEventListener("mouseleave", () => {
    clearTimeout(timer);
    if (cycle) { clearInterval(cycle); cycle = null; }
    if (loaded) { const ov = thumb.querySelector(".hover-prev"); if (ov) ov.classList.remove("on"); }
  });
}
