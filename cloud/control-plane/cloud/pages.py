"""Server-rendered HTML for the control-plane (landing, pricing, signup, login,
donate, dashboard, and the post-checkout pages). No template engine — plain f-strings
with html.escape on anything dynamic. Brand voice + tokens mirror docs/BRAND.md."""
from __future__ import annotations
import html
import time

from . import const


def _esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def money(cents):
    cents = int(cents or 0)
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def _mockbar():
    if not const.MOCK:
        return ""
    return ('<div class="mockbar">Running in <b>MOCK</b> mode — no real payments. '
            'Set <code>STRIPE_SECRET_KEY</code> to go live. See cloud/README.md.</div>')


def layout(title, body, account=None):
    if account:
        right = ('<a href="/dashboard">Dashboard</a>'
                 '<form method="post" action="/api/logout" style="display:inline">'
                 '<button class="btn ghost" type="submit">Sign out</button></form>')
    else:
        right = '<a href="/pricing">Pricing</a><a href="/donate">Donate</a><a href="/login">Sign in</a>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="Kadmu Cloud — the personal media player that's private and free as Jellyfin, easy as Plex, with the per-file power of VLC. Remote access that just works.">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/style.css">
</head>
<body>
{_mockbar()}
<header class="bar"><div class="wrap">
  <a class="brand" href="/"><img src="/favicon.svg" alt=""> Kadmu <span class="cloud">Cloud</span></a>
  <nav class="links">{right}</nav>
</div></header>
{body}
<footer><div class="wrap">
  <span>© {time.gmtime().tm_year} Pentarosa Co. — Kadmu Cloud {const.APP_VERSION}</span>
  <nav>
    <a href="/">Home</a><a href="/pricing">Pricing</a><a href="/donate">Donate</a>
    <a href="https://github.com/">Open source</a>
  </nav>
</div></footer>
</body>
</html>"""


# --------------------------------------------------------------------------- #
def landing():
    body = """
<section class="hero"><div class="wrap">
  <span class="eyebrow">your files · your machine · your cinema</span>
  <h1>The personal cinema that just works — from anywhere.</h1>
  <p class="lede">Kadmu plays <b>your</b> video files beautifully: VLC-grade power, Netflix-grade
    ease, in a browser tab. Self-host it free, or let <b>Kadmu Cloud</b> handle accounts, billing,
    and (soon) remote access that works without port-forwarding — while your videos never leave
    your machine.</p>
  <div class="cta">
    <a class="btn primary lg" href="/pricing">Start Kadmu Cloud</a>
    <a class="btn lg" href="https://github.com/">Self-host for free</a>
  </div>
  <p class="fineprint">Pay-first, cancel anytime. The open-source player is, and always will be, free.</p>
</div></section>

<section class="alt"><div class="wrap">
  <h2>Why Cloud, when the app is free?</h2>
  <p class="muted">Because we monetize the hosting, never the features. Everything in the player is
    open and unlocked. Cloud is the convenience layer.</p>
  <div class="grid3">
    <div class="card pillar"><div class="ic">⚡</div><h3>Effortless accounts</h3>
      <p class="muted">Managed multi-user accounts and sign-in, kept in sync — no DB to babysit,
        no reverse proxy to configure.</p></div>
    <div class="card pillar"><div class="ic">∞</div><h3>Remote that just works</h3>
      <p class="muted">Watch from anywhere without port-forwarding or DDNS. Peer-to-peer, so your
        video streams straight from your machine — we never touch the bytes.
        <span class="small">(P2P remote ships next.)</span></p></div>
    <div class="card pillar"><div class="ic">🔒</div><h3>Yours &amp; private</h3>
      <p class="muted">No ads, no upsells, no phone-home. Your library stays your folders; your
        files never live on our servers. We host the <i>account</i>, not your content.</p></div>
  </div>
</div></section>

<section><div class="wrap narrow" style="text-align:center">
  <h2>How it works</h2>
  <p class="muted">1. Subscribe. &nbsp;2. Run the open-source Kadmu node on your machine, signed in to
    your Cloud account. &nbsp;3. Watch your library — at home on the LAN today, from anywhere soon.</p>
  <div class="cta" style="justify-content:center;margin-top:18px">
    <a class="btn primary lg" href="/pricing">See pricing</a>
  </div>
</div></section>
"""
    return layout("Kadmu Cloud — your personal cinema, from anywhere", body)


def _per(p):
    return {"month": "/mo", "year": "/yr", "once": " once"}.get(p.get("interval"), "")


def _plan_by(tier, cadence):
    for p in const.PLANS.values():
        if p.get("tier") == tier and p.get("cadence") == cadence:
            return p
    return None


# Human "what's included" bullets per tier (the license features in plain English).
_GiB = 1024 ** 3
_TIER_BULLETS = {
    "plus":   ["Watch from anywhere (peer-to-peer)", "1 home", "Share-a-link to one title",
               "Managed metadata &amp; subtitles", "Off-site settings backup"],
    "family": ["Everything in Plus", "Up to 3 homes", "Sharp 1080p relay", "More relay headroom"],
    "pro":    ["Everything in Family", "Up to 5 homes", "Top relay quality &amp; cap", "Priority support"],
}
_TIER_TAG = {"family": '<span class="tag">Most popular</span>'}


def pricing():
    cards = []
    for tier in const.PRICING_TIERS:
        m = _plan_by(tier, "monthly")
        y = _plan_by(tier, "yearly")
        if not m:
            continue
        featured = tier == "family"
        cap_gib = (m.get("relay_cap_bytes", 0)) // _GiB
        bullets = list(_TIER_BULLETS.get(tier, []))
        bullets.append(f"{cap_gib} GB/mo relay · {m.get('relay_max_height', 720)}p")
        yr = f'<div class="muted small">or {money(y["price_cents"])}/yr — two months free</div>' if y else ""
        cards.append(f"""
    <div class="card plan{' featured' if featured else ''}">{_TIER_TAG.get(tier, '')}
      <h3>{_esc(m['name'])}</h3>
      <div class="price">{money(m['price_cents'])}<span class="per">/mo</span></div>
      {yr}
      <ul class="feat">{''.join(f'<li>{b}</li>' for b in bullets)}</ul>
      <a class="btn primary block" href="/signup?plan={_esc(m['id'])}">Get {_esc(m['name'])}</a>
    </div>""")

    life = const.PLANS.get(const.PRICING_LIFETIME)
    life_card = ""
    if life:
        life_card = f"""
  <div class="card plan lifetime">
    <h3>{_esc(life['name'])}</h3>
    <div class="price">{money(life['price_cents'])}<span class="per"> once</span></div>
    <div class="muted small">No subscription. Ever.</div>
    <ul class="feat">
      <li>Watch from anywhere (peer-to-peer)</li><li>1 home</li>
      <li>Share-a-link, managed metadata &amp; backup</li>
      <li>Modest relay ({life.get('relay_cap_bytes', 0) // _GiB} GB/mo · {life.get('relay_max_height', 720)}p)</li>
    </ul>
    <a class="btn block" href="/signup?plan={_esc(life['id'])}">Buy {_esc(life['name'])}</a>
  </div>"""

    body = f"""
<section><div class="wrap">
  <div style="text-align:center;margin-bottom:8px"><h1>Simple pricing</h1>
  <p class="muted">Pay first, cancel anytime. The self-hosted player stays free forever — Cloud adds the remote connection.</p></div>
  <div class="plans">{''.join(cards)}</div>
  <div class="plans" style="margin-top:14px">{life_card}</div>
  <p class="muted small" style="text-align:center;margin-top:24px">
    Your video never flows through our servers — it streams peer-to-peer from your machine, so our cost (and your privacy exposure) stays tiny.
    Prefer to run it yourself? <a href="https://github.com/">Self-host Kadmu</a> is free and open source.
    Want to support that instead? <a href="/donate">Donate</a>.</p>
</div></section>
"""
    return layout("Pricing — Kadmu Cloud", body)


def signup(plan="monthly", error="", email=""):
    if plan not in const.PLANS:
        plan = const.DEFAULT_PLAN
    p = const.PLANS[plan]
    per = _per(p)
    err = f'<div class="notice err">{_esc(error)}</div>' if error else ""
    body = f"""
<section><div class="wrap narrow">
  <h1>Create your account</h1>
  <p class="muted">{_esc(p['name'])} · {_esc(p['cadence'].title())} — <b>{money(p['price_cents'])}{per}</b>.
    You'll be sent to secure checkout; access activates the moment payment succeeds.</p>
  {err}
  <form class="stack" method="post" action="/api/signup">
    <input type="hidden" name="plan" value="{_esc(plan)}">
    <div class="field"><label for="email">Email</label>
      <input id="email" name="email" type="email" required autocomplete="email" value="{_esc(email)}"></div>
    <div class="field"><label for="password">Password</label>
      <input id="password" name="password" type="password" required minlength="8"
        autocomplete="new-password"></div>
    <button class="btn primary block lg" type="submit">Continue to payment →</button>
  </form>
  <p class="muted small" style="margin-top:14px">Already subscribed? <a href="/login">Sign in</a>.
    Switch plan: <a href="/signup?plan={'yearly' if plan=='monthly' else 'monthly'}">
    {'yearly' if plan=='monthly' else 'monthly'}</a>.</p>
</div></section>
"""
    return layout("Sign up — Kadmu Cloud", body)


def login(error="", email=""):
    err = f'<div class="notice err">{_esc(error)}</div>' if error else ""
    body = f"""
<section><div class="wrap narrow">
  <h1>Sign in</h1>
  <p class="muted">Access your Kadmu Cloud dashboard, billing, and node connection details.</p>
  {err}
  <form class="stack" method="post" action="/api/login">
    <div class="field"><label for="email">Email</label>
      <input id="email" name="email" type="email" required autocomplete="email" value="{_esc(email)}"></div>
    <div class="field"><label for="password">Password</label>
      <input id="password" name="password" type="password" required autocomplete="current-password"></div>
    <button class="btn primary block lg" type="submit">Sign in</button>
  </form>
  <p class="muted small" style="margin-top:14px">No account yet? <a href="/pricing">See pricing</a>.</p>
</div></section>
"""
    return layout("Sign in — Kadmu Cloud", body)


def donate(error=""):
    err = f'<div class="notice err">{_esc(error)}</div>' if error else ""
    opts = []
    for i, cents in enumerate(const.DONATION_PRESETS_CENTS):
        checked = " checked" if i == 1 else ""
        opts.append(f'<label><input type="radio" name="preset" value="{cents}"{checked}>'
                    f'<span class="opt">{money(cents)}</span></label>')
    body = f"""
<section><div class="wrap narrow">
  <h1>Support the open-source Kadmu</h1>
  <p class="muted">Donations fund the free, self-hostable player — separate from Cloud subscriptions.
    No account needed. Thank you. 🧡</p>
  {err}
  <form class="stack" method="post" action="/api/donate">
    <div class="field"><label>Amount</label>
      <div class="amounts">{''.join(opts)}
        <label><input type="radio" name="preset" value="custom"><span class="opt">Other</span></label>
      </div></div>
    <div class="field"><label for="custom">Custom amount (USD)</label>
      <input id="custom" name="custom" type="number" min="1" step="1" placeholder="e.g. 25"></div>
    <div class="field"><label for="email">Email (optional, for a receipt)</label>
      <input id="email" name="email" type="email" autocomplete="email"></div>
    <button class="btn primary block lg" type="submit">Donate →</button>
  </form>
</div></section>
"""
    return layout("Donate — Kadmu", body)


def dashboard(account, sub, tenant, plan_id, status_badge, manage_note=""):
    name = _esc(account.get("name") or account.get("email"))
    run_cmd = (f"KADMU_CLOUD_URL={const.BASE_URL} \\\n"
               f"KADMU_CLOUD_TENANT={tenant['id']} \\\n"
               f"KADMU_CLOUD_SECRET={tenant['secret']} \\\n"
               f"python3 src/server.py --accounts ~/Videos")
    if sub:
        plan = const.PLANS.get(plan_id, const.PLANS[const.DEFAULT_PLAN])
        renew = time.strftime("%b %-d, %Y", time.gmtime(sub["current_period_end"])) \
            if sub["current_period_end"] else "—"
        cap = " (cancels at period end)" if sub["cancel_at_period_end"] else ""
        sub_block = f"""
      <dl class="kv">
        <dt>Plan</dt><dd>{_esc(plan['name'])} · {_esc(plan['cadence'])}</dd>
        <dt>Status</dt><dd>{status_badge}{_esc(cap)}</dd>
        <dt>Renews</dt><dd>{_esc(renew)}</dd>
      </dl>
      <form method="post" action="/api/billing-portal" style="display:inline">
        <button class="btn" type="submit">Manage billing</button></form>"""
    else:
        sub_block = """
      <p class="muted">No active subscription. <a href="/pricing">Choose a plan</a> to activate your node.</p>"""
    tenant_block = f"""
      <p class="muted">Run the open-source Kadmu node on your machine with these credentials and it
        will validate your subscription automatically (with a 7-day offline grace window).
        <b>Keep the secret private.</b></p>
      <dl class="kv">
        <dt>Tenant ID</dt><dd>{_esc(tenant['id'])}</dd>
        <dt>Secret</dt><dd>{_esc(tenant['secret'])}</dd>
        <dt>Cloud URL</dt><dd>{_esc(const.BASE_URL)}</dd>
      </dl>
      <pre>{_esc(run_cmd)}</pre>""" if tenant else "<p class='muted'>Your node will be provisioned once your subscription is active.</p>"
    note = f'<div class="notice ok">{_esc(manage_note)}</div>' if manage_note else ""
    body = f"""
<section><div class="wrap">
  <h1>Welcome, {name}</h1>
  {note}
  <div class="grid3" style="grid-template-columns:1fr;max-width:720px">
    <div class="card"><h3>Subscription</h3>{sub_block}</div>
    <div class="card"><h3>Connect your node</h3>{tenant_block}</div>
  </div>
</div></section>
"""
    return layout("Dashboard — Kadmu Cloud", body, account=account)


def checkout_success():
    body = """
<section><div class="wrap narrow" style="text-align:center">
  <div class="badge ok">Payment received</div>
  <h1>You're in. 🎬</h1>
  <p class="muted">Your subscription is active. Head to your dashboard for your node connection
    details and to manage billing.</p>
  <div class="cta" style="justify-content:center"><a class="btn primary lg" href="/dashboard">Go to dashboard</a></div>
</div></section>
"""
    return layout("Welcome — Kadmu Cloud", body)


def checkout_cancel():
    body = """
<section><div class="wrap narrow" style="text-align:center">
  <h1>Checkout cancelled</h1>
  <p class="muted">No charge was made. You can pick a plan whenever you're ready.</p>
  <div class="cta" style="justify-content:center"><a class="btn primary lg" href="/pricing">Back to pricing</a></div>
</div></section>
"""
    return layout("Cancelled — Kadmu Cloud", body)


def donate_thanks(amount_cents=0):
    amt = f" of {money(amount_cents)}" if amount_cents else ""
    body = f"""
<section><div class="wrap narrow" style="text-align:center">
  <div class="badge ok">Thank you 🧡</div>
  <h1>Your donation{_esc(amt)} keeps Kadmu free.</h1>
  <p class="muted">It funds the open-source player everyone gets to keep. We appreciate you.</p>
  <div class="cta" style="justify-content:center"><a class="btn lg" href="/">Back home</a></div>
</div></section>
"""
    return layout("Thank you — Kadmu", body)


def error_page(title, message, status=400):
    body = f"""
<section><div class="wrap narrow" style="text-align:center">
  <h1>{_esc(title)}</h1>
  <p class="muted">{_esc(message)}</p>
  <div class="cta" style="justify-content:center"><a class="btn lg" href="/">Back home</a></div>
</div></section>
"""
    return layout(f"{title} — Kadmu Cloud", body)
