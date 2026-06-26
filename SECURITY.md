# Security policy

## Reporting a vulnerability

Please email **security@mezi.app** (or open a private security advisory on GitHub).
We aim to respond within a few days. Please don't open public issues for vulnerabilities.

## Threat model

Kinema is a **self-hosted personal media app**. It is designed to be safe when run:

1. on your own machine (localhost), and
2. on a trusted home network (LAN) behind an optional password.

It is **not** designed to be a public, multi-tenant service exposed directly to the
internet. If you expose it publicly, do so behind a reverse proxy with HTTPS, set a strong
`--password`, and prefer `--read-only`.

## Protections built in

| Risk | Mitigation |
|------|-----------|
| **Path traversal** | Every file path from the client is resolved (`realpath`) and must fall inside a configured library root, or it's rejected. |
| **CSRF / DNS-rebinding** | The `Host` header is checked against an allow-list (localhost + the machine's own LAN IPs; real private IPs only in `--lan` mode). State-changing requests also require a positive same-site signal — a custom `X-Kinema` header that cross-site pages cannot set without a CORS preflight we never grant, or a same-site `Origin`/`Referer`. This blocks malicious websites from driving the local server. |
| **Unauthenticated access** | Optional password (`--password`). When set, all non-login routes require a `HttpOnly`, `SameSite=Strict` session cookie. Sessions expire (30 days) and are capped in number; wrong-password attempts are throttled per source IP with exponential backoff/lockout, and the password compare is constant-time. |
| **Destructive file ops** | Rename/move/delete/mkdir and config changes are disabled entirely in `--read-only` mode and require auth otherwise. Deletes move to a `.kinema-trash` folder (reversible), never `rm`. |
| **Server-side folder browser** | The `/api/browse` picker (which can see directory names outside the library) is disabled in read-only mode and requires auth. |
| **XSS** | All user/file-derived strings are HTML-escaped before rendering, and a strict `Content-Security-Policy` (`script-src 'self'`, no inline scripts) is sent with the app. |
| **Resource exhaustion** | Concurrent `ffmpeg` thumbnail jobs are capped; request bodies are size-limited; video is streamed in bounded chunks with proper HTTP Range handling. |
| **Clickjacking / sniffing** | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. |
| **Command injection** | `ffmpeg`/`ffprobe` are invoked as argument vectors (never a shell) with `--` before filenames. |

## What Kinema does NOT do

- No TLS/HTTPS itself — terminate TLS at a reverse proxy if exposing beyond your LAN.
- No multi-user accounts or per-user libraries — a single shared password, by design.
- No outbound network calls — it never phones home.
