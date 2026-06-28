# Deploying Kadmu

Kadmu is built for **localhost + a trusted LAN**. Anything more exposed needs HTTPS
and a password (or accounts). Two supported TLS paths:

## 1. Reverse proxy (recommended for public exposure)

Put Kadmu behind [Caddy](https://caddyserver.com) (or nginx/Traefik) and let it
terminate TLS with automatic certificates. See [`Caddyfile`](Caddyfile) for a
complete example.

```bash
# Kadmu: bind loopback, allow-list the public domain, require auth
KADMU_ALLOWED_HOSTS=kadmu.example.com KADMU_PASSWORD=change-me \
  python3 src/server.py /path/to/Videos --host 127.0.0.1 --port 8000 --no-open

# Caddy: auto-HTTPS + proxy to Kadmu
caddy run --config deploy/Caddyfile
```

Kadmu sees the proxy connecting from `127.0.0.1`, so it stays loopback-only and the
in-app LAN toggle is irrelevant; the public hostname just has to be in
`KADMU_ALLOWED_HOSTS`. Because all traffic arrives as loopback, do **public rate
limiting at the proxy** — Kadmu's built-in per-IP limiter exempts loopback.

## 2. Built-in TLS (direct LAN serving)

For serving HTTPS directly on your LAN without a proxy, point Kadmu at a cert + key:

```bash
# self-signed cert for a LAN box (browsers will warn once; that's expected)
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem \
  -days 825 -subj "/CN=$(hostname)"

python3 src/server.py /path/to/Videos --lan --tls cert.pem key.pem --password change-me
# or via env: KADMU_TLS_CERT=cert.pem KADMU_TLS_KEY=key.pem
```

Every URL Kadmu prints/serves then uses `https://`. (Built-in TLS sends no HSTS so a
self-signed cert can't lock a browser out of the host; for public HSTS use the proxy.)

## Ops endpoints

- `GET /healthz` — unauthenticated liveness probe (bypasses host/auth/rate-limit so
  monitors and load balancers always work). Returns `{"status":"ok", ...}`.
- `GET /metrics` — Prometheus text metrics (requests, response classes, bytes served,
  errors, active streams, rate-limited/stream-rejected counts, per-user bytes in
  accounts mode). Readable without a session from loopback (local scraping); from
  off-box it requires auth (admin in accounts mode).
- `--log-requests` (or `KADMU_LOG_REQUESTS=1`) emits one structured JSON line per
  request to stdout, or to `KADMU_ACCESS_LOG=/path/to/file`.

## Docker (public read-only demo)

See [`docker-compose.yml`](docker-compose.yml). Build context **must** be the project
root. Terminate HTTPS at a proxy in front of the container.
