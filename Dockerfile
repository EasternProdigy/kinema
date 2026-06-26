# Docker image for the public Kinema DEMO (read-only, sample content).
# Not required for normal use — desktop users just double-click a launcher.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server.py ./
COPY web ./web
COPY scripts ./scripts

# Bake in the royalty-free sample library at build time (same generator the
# in-app `--demo` mode uses).
RUN python -c "from pathlib import Path; import server; server.build_demo_library(Path('/app/demo-library'))"

ENV KINEMA_PORT=8000 KINEMA_READONLY=1
EXPOSE 8000

# Read-only + no folder browsing. Host checking is relaxed because this is a
# public, read-only, sample-only demo (nothing private to protect). To lock it
# to a domain instead, drop --allow-any-host and set KINEMA_ALLOWED_HOSTS.
CMD ["python", "server.py", "/app/demo-library", \
     "--host", "0.0.0.0", "--read-only", "--no-browse", \
     "--no-open", "--allow-any-host"]
