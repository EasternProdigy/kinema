"""The control-plane HTTP handler: marketing pages, the pay-first signup funnel,
dashboard, the Stripe webhook, and the machine-to-machine /api/license endpoint a
tenant's node polls. One BaseHTTPRequestHandler subclass, plain if/elif routing —
same spirit as the node's handler."""
from __future__ import annotations
import ipaddress
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import (accounts, const, entitlements, pages, relaycreds, stripe_client, webhooks)
from .db import db

CSP = ("default-src 'self'; img-src 'self'; style-src 'self'; script-src 'none'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

STATIC = {
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"KadmuCloud/{const.APP_VERSION}"
    timeout = 30

    def log_message(self, fmt, *args):
        pass

    # -- responses ---------------------------------------------------------- #
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def _send(self, body, ctype, status=200, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, html_str, status=200, extra=None):
        self._send(html_str, "text/html; charset=utf-8", status, extra)

    def _json(self, obj, status=200, extra=None):
        self._send(json.dumps(obj), "application/json; charset=utf-8", status, extra)

    def _redirect(self, location, status=303, extra=None):
        headers = {"Location": location}
        headers.update(extra or {})
        self.send_response(status)
        self.send_header("Content-Length", "0")
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()

    # -- request parsing ---------------------------------------------------- #
    def _raw_body(self):
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return b""
        if n <= 0 or n > 1_000_000:
            return b""
        return self.rfile.read(n)

    def _form(self):
        data = self._raw_body().decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(data).items()}

    def _json_body(self):
        try:
            return json.loads(self._raw_body() or b"{}")
        except (ValueError, TypeError):
            return {}

    def _cookies(self):
        out = {}
        for part in (self.headers.get("Cookie", "") or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def _account(self):
        tok = self._cookies().get(const.SESSION_COOKIE)
        aid = accounts.session_account(tok) if tok else None
        return accounts.get_account(aid) if aid is not None else None

    def _origin_ok(self):
        """Same-site check for authenticated state-changing actions."""
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if not origin:
            return False
        host = urlparse(origin).netloc.lower()
        return host == (self.headers.get("Host", "") or "").lower()

    # -- verbs -------------------------------------------------------------- #
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        route, qs = parsed.path, parse_qs(parsed.query)

        if route in STATIC:
            return self._static(route)
        if route == "/healthz":
            return self._json({"ok": True, "app": const.APP_NAME,
                               "version": const.APP_VERSION, "mock": const.MOCK})
        if route == "/metrics":
            return self._metrics()
        if route == "/api/relay-credentials":
            return self._relay_credentials(qs)
        if route in ("/", "/index.html"):
            return self._html(pages.landing())
        if route == "/pricing":
            return self._html(pages.pricing())
        if route == "/signup":
            return self._html(pages.signup(qs.get("plan", [const.DEFAULT_PLAN])[0]))
        if route == "/login":
            if self._account():
                return self._redirect("/dashboard")
            return self._html(pages.login())
        if route == "/donate":
            return self._html(pages.donate())
        if route == "/dashboard":
            return self._dashboard()
        if route == "/checkout/success":
            return self._checkout_success(qs)
        if route == "/checkout/cancel":
            return self._html(pages.checkout_cancel())
        if route == "/donate/thanks":
            return self._donate_thanks(qs)
        return self._html(pages.error_page("Not found", "That page doesn't exist.", 404), 404)

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/api/signup":
            return self._signup()
        if route == "/api/login":
            return self._login()
        if route == "/api/logout":
            return self._logout()
        if route == "/api/donate":
            return self._donate()
        if route == "/api/billing-portal":
            return self._billing_portal()
        if route == "/api/webhook/stripe":
            return self._webhook()
        if route == "/api/license":
            return self._license()
        return self._json({"error": "not found"}, 404)

    # -- static ------------------------------------------------------------- #
    def _static(self, route):
        name, ctype = STATIC[route]
        fp = const.WEB_DIR / name
        if not fp.is_file():
            return self._json({"error": "missing asset"}, 404)
        self._send(fp.read_bytes(), ctype, extra={"Cache-Control": "public, max-age=3600"})

    # -- funnel ------------------------------------------------------------- #
    def _signup(self):
        form = self._form()
        email = (form.get("email") or "").strip()
        password = form.get("password") or ""
        plan_id = form.get("plan") or const.DEFAULT_PLAN
        if plan_id not in const.PLANS:
            plan_id = const.DEFAULT_PLAN
        acct = accounts.get_account_by_email(email)
        if acct is None:
            pub, err = accounts.create_account(email, password)
            if err:
                return self._html(pages.signup(plan_id, error=err, email=email), 400)
        else:
            # Existing email: only proceed if the password matches (don't leak existence
            # otherwise, and don't let a stranger start checkout against someone's email).
            if accounts.auth_account(email, password) is None:
                return self._html(pages.signup(
                    plan_id, error="An account with that email already exists. "
                    "Use your existing password, or sign in.", email=email), 400)
        plan = const.PLANS[plan_id]
        customer = (acct or {}).get("stripe_customer") if acct else None
        success, cancel = f"{const.BASE_URL}/checkout/success", f"{const.BASE_URL}/checkout/cancel"
        try:
            if plan.get("one_time"):                      # lifetime → one-time payment
                url, _sid = stripe_client.create_onetime_checkout(plan, email, customer, success, cancel)
            else:                                         # Plus/Family/Pro → subscription
                url, _sid = stripe_client.create_subscription_checkout(plan, email, customer, success, cancel)
        except stripe_client.StripeError as e:
            return self._html(pages.signup(plan_id, error=f"Payment setup failed: {e}", email=email), 502)
        return self._redirect(url)

    def _login(self):
        form = self._form()
        email = (form.get("email") or "").strip()
        row = accounts.auth_account(email, form.get("password") or "")
        if row is None:
            return self._html(pages.login(error="Wrong email or password.", email=email), 401)
        tok = accounts.new_session(row["id"])
        return self._redirect("/dashboard", extra={"Set-Cookie": accounts.session_cookie(tok)})

    def _logout(self):
        tok = self._cookies().get(const.SESSION_COOKIE)
        if tok:
            accounts.logout(tok)
        return self._redirect("/", extra={"Set-Cookie": accounts.CLEAR_COOKIE})

    def _donate(self):
        form = self._form()
        preset = form.get("preset") or ""
        if preset == "custom" or not preset:
            try:
                cents = int(round(float(form.get("custom") or 0) * 100))
            except (TypeError, ValueError):
                cents = 0
        else:
            try:
                cents = int(preset)
            except ValueError:
                cents = 0
        if cents < const.DONATION_MIN_CENTS or cents > const.DONATION_MAX_CENTS:
            return self._html(pages.donate(error="Enter an amount of at least $1."), 400)
        email = (form.get("email") or "").strip()
        try:
            url, _sid = stripe_client.create_donation_checkout(
                cents, email, f"{const.BASE_URL}/donate/thanks", f"{const.BASE_URL}/donate")
        except stripe_client.StripeError as e:
            return self._html(pages.donate(error=f"Couldn't start checkout: {e}"), 502)
        return self._redirect(url)

    def _billing_portal(self):
        acct = self._account()
        if not acct:
            return self._redirect("/login")
        if not self._origin_ok():
            return self._html(pages.error_page("Blocked", "Cross-site request blocked.", 403), 403)
        url = stripe_client.billing_portal_url(acct.get("stripeCustomer"),
                                               f"{const.BASE_URL}/dashboard")
        return self._redirect(url)

    # -- dashboard ---------------------------------------------------------- #
    def _dashboard(self):
        acct = self._account()
        if not acct:
            return self._redirect("/login")
        sub = entitlements.active_subscription(acct["id"])
        tenant = None
        if sub:
            tenant = entitlements.provision_tenant(acct["id"])
        plan_id = sub["plan"] if sub else const.DEFAULT_PLAN
        badge = self._status_badge(sub)
        note = ""
        if urlparse(self.path).query and "portal=mock" in self.path:
            note = "Billing portal is stubbed in mock mode — set Stripe keys to enable it."
        return self._html(pages.dashboard(acct, sub, tenant, plan_id, badge, manage_note=note))

    @staticmethod
    def _status_badge(sub):
        if not sub:
            return '<span class="badge off">none</span>'
        s = sub["status"]
        if s in ("active", "trialing"):
            return f'<span class="badge ok">{s}</span>'
        if s == "past_due":
            return '<span class="badge warn">past due</span>'
        return f'<span class="badge off">{s}</span>'

    # -- post-checkout (mock replays the webhook here so the flow completes) -- #
    def _checkout_success(self, qs):
        if const.MOCK and qs.get("mock"):
            sid = qs.get("session_id", [""])[0]
            # Reconstruct enough of a Stripe session for the webhook processor. The
            # email/plan are carried in the success URL only in mock mode (we can't
            # ask the real Stripe), so re-derive from the most recent pending intent.
            obj = self._mock_session_for(sid, qs.get("plan", [""])[0])
            if obj:
                webhooks.process_event(stripe_client.synth_event("checkout.session.completed", obj))
        return self._html(pages.checkout_success())

    def _donate_thanks(self, qs):
        amount = 0
        if const.MOCK and qs.get("mock"):
            sid = qs.get("session_id", [""])[0]
            try:
                amount = int(qs.get("amount", ["0"])[0])
            except ValueError:
                amount = 0
            obj = {"id": sid, "mode": "payment", "amount_total": amount,
                   "currency": "usd", "_amount": amount}
            webhooks.process_event(stripe_client.synth_event("checkout.session.completed", obj))
        return self._html(pages.donate_thanks(amount))

    def _mock_session_for(self, sid, plan=""):
        """In mock mode the success URL is hit by the browser with a session id + the
        chosen plan. We pair it with the account that most recently started signup (the
        one without a subscription yet) so the demo flow provisions the right tier."""
        row = db().execute(
            "SELECT a.email, a.stripe_customer FROM accounts a "
            "LEFT JOIN subscriptions s ON s.account_id=a.id "
            "WHERE s.id IS NULL ORDER BY a.created DESC LIMIT 1").fetchone()
        # Fall back to the signed-in account (e.g. re-subscribe), if any.
        if row is None:
            acct = self._account()
            if not acct:
                return None
            email, customer = acct["email"], acct.get("stripeCustomer")
        else:
            email, customer = row["email"], row["stripe_customer"]
        plan = plan if plan in const.PLANS else const.DEFAULT_PLAN
        obj = {"id": sid, "customer": customer, "customer_email": email,
               "client_reference_id": plan, "metadata": {"plan": plan}}
        if const.PLANS[plan].get("one_time"):
            obj["mode"] = "payment"                        # lifetime → one-time purchase
        else:
            obj["mode"] = "subscription"
            obj["subscription"] = "sub_mock_" + sid.split("_")[-1]
        return obj

    # -- webhook (real Stripe events) --------------------------------------- #
    def _webhook(self):
        raw = self._raw_body()
        event = stripe_client.verify_webhook(raw, self.headers.get("Stripe-Signature", ""))
        if event is None:
            return self._json({"error": "invalid signature"}, 400)
        try:
            result = webhooks.process_event(event)
        except Exception as e:
            return self._json({"error": str(e)}, 500)
        return self._json({"ok": True, "result": result})

    # -- machine-to-machine license issuance (the node polls this) ---------- #
    def _license(self):
        body = self._json_body()
        tenant = entitlements.verify_tenant_proof(
            body.get("tenant"), body.get("ts"), body.get("sig"))
        if tenant is None:
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        token, payload = entitlements.license_for_tenant(tenant)
        if token is None:
            return self._json({"ok": False, "status": "inactive", "reason": payload}, 402)
        return self._json({"ok": True, "license": token, "exp": payload["exp"],
                           "grace": payload["grace"], "issued": int(time.time())})

    # -- Phase 5: entitlement-bound TURN credentials (the relay cap gate) ---- #
    def _relay_credentials(self, qs):
        """Mint short-lived TURN credentials for an entitled, under-cap tenant — or refuse
        (STUN-only) when the plan grants no relay / the cap is reached / the sub is inactive.
        Two callers, two auth paths: the node's connector proves possession of the tenant
        secret (tenant/ts/sig, same scheme as /api/license); the owner's browser uses its
        dashboard session. See cloud/metering/ and cloud/README.md (Scale & cost control)."""
        now = time.time()
        t = (qs.get("tenant") or [""])[0]
        ts = (qs.get("ts") or [""])[0]
        sig = (qs.get("sig") or [""])[0]
        if t or ts or sig:                       # machine path: tenant proof
            row = entitlements.verify_tenant_proof(t, ts, sig)
            if row is None:
                return self._json({"relay": False, "reason": "unauthorized"}, 401)
            account_id, tenant_id = row["account_id"], row["id"]
        else:                                    # browser path: dashboard session
            acct = self._account()
            if not acct:
                return self._json({"relay": False, "reason": "unauthorized",
                                   "needAuth": True}, 401)
            account_id = acct["id"]
            tenant_id = (entitlements.provision_tenant(account_id) or {}).get("id")
        sub = entitlements.active_subscription(account_id)
        if sub is None or not tenant_id:
            return self._json({"relay": False, "reason": "no_active_subscription"}, 402)
        return self._json(relaycreds.relay_credentials(tenant_id, sub["plan"], now))

    # -- Phase 5: Prometheus metrics (relay metering + control-plane gauges) - #
    def _metrics(self):
        """Scrape endpoint for cloud/infra/observability. Readable from loopback or a private
        network (the internal Prometheus container); a public scrape is refused unless
        KADMU_CLOUD_METRICS_OPEN is set. Exposes only aggregate counts, never secrets."""
        ip = self.client_address[0] if self.client_address else ""
        if os.environ.get("KADMU_CLOUD_METRICS_OPEN", "") not in ("1", "true", "yes"):
            try:
                addr = ipaddress.ip_address(ip)
                allowed = addr.is_loopback or addr.is_private
            except ValueError:
                allowed = False
            if not allowed:
                return self._json({"error": "forbidden"}, 403)
        self._send(relaycreds.metrics_text(time.time()),
                   "text/plain; version=0.0.4; charset=utf-8")
