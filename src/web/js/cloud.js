/* Kadmu Cloud — frontend surface (Phase 4a).
   Only relevant when the node runs cloud-attached (state.session.cloud === true).
   Self-host instances never set that flag, so everything here is a no-op for them.

   The node's security gate returns 402 {needSub} for every protected route while the
   instance's subscription is inactive; the app shell + /api/session still load, so we
   show a clear, brand-true notice and a "Manage billing" link to the Cloud dashboard.
   Classic script, shares globals (see index.html load order; loads before main.js). */

/* Read the latest session and reflect cloud entitlement in the UI. Called from
   applySession() (main.js) and after the session is refreshed. */
function applyCloud() {
  const s = state.session || {};
  if (!s.cloud) { hideCloudInactive(); return; }
  const ent = s.entitlement || {};
  if (ent.active) hideCloudInactive();
  else showCloudInactive(ent);
}

function showCloudInactive(ent) {
  ent = ent || {};
  const ov = $("#cloudOverlay");
  if (!ov) return;
  const hint = $("#cloudHint"), title = $("#cloudTitle"), manage = $("#cloudManage");
  const map = {
    inactive: "This Kadmu Cloud instance has no active subscription. Renew to keep watching.",
    expired:  "Your license has expired and we can't reach Kadmu Cloud to refresh it. " +
              "Reconnect this machine to the internet, or renew your subscription.",
    pending:  "We haven't been able to verify your subscription with Kadmu Cloud yet.",
    unverified: "We couldn't verify your subscription with Kadmu Cloud.",
    grace:    "",  // grace is active — no overlay
  };
  if (title) title.textContent = ent.status === "expired" ? "License expired" : "Subscription inactive";
  if (hint) hint.textContent = map[ent.status] || map.unverified;
  const err = $("#cloudError");
  if (err) err.textContent = ent.reason && ent.status !== "inactive" ? ("(" + ent.reason + ")") : "";
  if (manage) manage.href = ent.manageUrl || "#";
  ov.classList.remove("hidden");
}

function hideCloudInactive() {
  const ov = $("#cloudOverlay");
  if (ov) ov.classList.add("hidden");
}

/* Wire the overlay's buttons once the DOM is ready. */
(function initCloud() {
  const retry = document.getElementById("cloudRetry");
  if (retry) retry.addEventListener("click", async () => {
    retry.disabled = true;
    try {
      if (typeof refreshSession === "function") await refreshSession();
      applyCloud();
      if (state.session && state.session.cloud && state.session.entitlement &&
          state.session.entitlement.active) {
        // Came back to life — reload so the gated UI re-initializes cleanly.
        location.reload();
      }
    } catch {} finally { retry.disabled = false; }
  });
})();
