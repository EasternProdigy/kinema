"use strict";
/* billing.js — the in-app monetization surface: the Settings → "Kadmu Cloud"
   section. Shows the current plan + "Manage billing" when this node is a paying
   Cloud tenant, or a "watch from anywhere" upsell + Support/Donate links for a
   self-host install. Pure links — no outbound calls; the whole thing hides when a
   host sets KADMU_SHOW_UPSELL=0. Classic script, shares globals (loads before main.js). */

// What each license feature flag means, for the "what's included" list.
const CLOUD_FEATURE_LABELS = {
  remote: "Watch from anywhere (peer-to-peer)",
  share_link: "Share a private link to one title",
  relay: "Relay fallback for tough networks",
  backup: "Off-site backup of your settings",
  metadata: "Managed metadata — no TMDB key to wrangle",
  subtitles: "Managed subtitle fetch",
  homes: "Connect multiple homes",
  priority_support: "Priority support",
};

// The marquee benefits shown to a self-host install (it has no license to read).
const CLOUD_UPSELL_BULLETS = [
  "Watch your library from anywhere — your bytes stream peer-to-peer, never through our servers",
  "Share a private, time-limited link to a single title",
  "Off-site backup of your settings &amp; watch history",
  "Managed metadata &amp; subtitles — nothing to key in",
];

function renderCloudBilling() {
  const sec = $("#cloudSection");
  if (!sec) return;
  const s = state.session || {};
  const up = s.upsell;
  const attached = !!s.cloud;
  // Host turned the whole surface off, and this isn't a Cloud tenant → nothing to show.
  if (!up && !attached) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  const box = $("#cloudControl");
  if (!box) return;

  if (attached) box.innerHTML = cloudTenantHtml(s);
  else box.innerHTML = cloudUpsellHtml(up);
  applyIcons(box);
}

// A node that's actually a Cloud tenant: plan, status, what's included, manage link.
function cloudTenantHtml(s) {
  const ent = s.entitlement || {};
  const feats = s.features || {};
  const active = !!ent.active;
  const statusText = {
    active: "Active", grace: "Active (offline grace)", trialing: "Trial",
    inactive: "Inactive — renew to keep watching", expired: "Expired",
    pending: "Verifying…", unverified: "Couldn't verify",
  }[ent.status] || (active ? "Active" : "Inactive");
  const included = Object.keys(CLOUD_FEATURE_LABELS)
    .filter(k => feats[k])
    .map(k => `<li>${ICON.check} ${CLOUD_FEATURE_LABELS[k]}</li>`).join("")
    || `<li class="muted">Managed accounts &amp; billing</li>`;
  const until = ent.until ? new Date(ent.until * 1000).toLocaleDateString() : "";
  return `
    <div class="cloud-card${active ? " on" : " off"}">
      <div class="cloud-card-head">
        <div>
          <div class="cloud-plan">${escapeHtml(s.planLabel || "Kadmu Cloud")}</div>
          <div class="cloud-status muted small">${escapeHtml(statusText)}${until && active ? " · renews " + escapeHtml(until) : ""}</div>
        </div>
        <a class="btn primary" href="${escapeHtml(ent.manageUrl || "#")}" target="_blank" rel="noopener">Manage billing</a>
      </div>
      <ul class="cloud-feat">${included}</ul>
    </div>`;
}

// A self-host install: advertise Cloud + a way to support the open-source side.
function cloudUpsellHtml(up) {
  up = up || {};
  const bullets = CLOUD_UPSELL_BULLETS.map(b => `<li>${ICON.check} ${b}</li>`).join("");
  return `
    <div class="cloud-card upsell">
      <div class="cloud-card-head">
        <div>
          <div class="cloud-plan">Kadmu Cloud</div>
          <div class="cloud-status muted small">Your library, from anywhere. The player stays free &amp; open — Cloud adds the remote connection.</div>
        </div>
        ${up.pricing ? `<a class="btn primary" href="${escapeHtml(up.pricing)}" target="_blank" rel="noopener">See plans</a>` : ""}
      </div>
      <ul class="cloud-feat">${bullets}</ul>
      <p class="muted small cloud-foot">Files never leave your machine — Cloud is just accounts, billing, and the connection handshake (so our cost, and your privacy exposure, stay tiny).
        ${up.donate ? `Prefer to chip in instead? <a href="${escapeHtml(up.donate)}" target="_blank" rel="noopener">Support Kadmu</a>.` : ""}</p>
    </div>`;
}

// "Where to watch" link for a title you don't own — used by the discover info sheet.
// Honest default: a plain JustWatch search. A host can set KADMU_AFFILIATE_WATCH
// (with {q}) to earn referral on the click. Returns "" when the upsell is hidden.
function whereToWatchUrl(name) {
  const up = (state.session || {}).upsell;
  if (!up) return "";
  const q = encodeURIComponent(name || "");
  if (up.affiliate) return up.affiliate.includes("{q}") ? up.affiliate.replace("{q}", q) : (up.affiliate + q);
  return "https://www.justwatch.com/us/search?q=" + q;
}
