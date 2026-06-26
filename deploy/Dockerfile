# Docker image for the public Kinema DEMO (read-only, sample content).
# Not required for normal use — desktop users just double-click a launcher.
#
# Build from the PROJECT ROOT (the build context must be the repo root):
#   docker build -f deploy/Dockerfile -t kinema-demo .
# or:
#   docker compose -f deploy/docker-compose.yml up --build
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Mirror the repo layout (src/server.py + src/web) so server.py keeps runtime
# state at the project root, which inside the container is /app.
COPY src/server.py ./src/server.py
COPY src/web ./src/web
COPY scripts ./scripts

# Bake in the royalty-free sample library at build time (same generator the
# in-app `--demo` mode uses).
RUN python -c "import sys; sys.path.insert(0, 'src'); from pathlib import Path; import server; server.build_demo_library(Path('/app/demo-library'))"

ENV KINEMA_PORT=8000 KINEMA_READONLY=1
EXPOSE 8000

# Drop root: run as an unprivileged user. The demo is already read-only, but
# defence in depth means a container break-in lands as "nobody", not root.
RUN useradd --system --uid 10001 --no-create-home kinema \
    && chown -R kinema:kinema /app
USER kinema

# Liveness probe — the same endpoint the CI boot smoke test asserts on.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if 'Kinema' in urllib.request.urlopen('http://127.0.0.1:8000/api/session',timeout=4).read().decode() else 1)"

# Read-only + no folder browsing. Host checking is relaxed because this is a
# public, read-only, sample-only demo (nothing private to protect). To lock it
# to a domain instead, drop --allow-any-host and set KINEMA_ALLOWED_HOSTS.
CMD ["python", "src/server.py", "/app/demo-library", \
     "--host", "0.0.0.0", "--read-only", "--no-browse", \
     "--no-open", "--allow-any-host"]
