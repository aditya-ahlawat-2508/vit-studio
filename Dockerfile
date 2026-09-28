# Vit Studio — runs anywhere Docker runs (Linux, macOS, Windows; amd64 or arm64).
#
#   docker compose up --build            → http://localhost:8765
#   docker build --target test .         → runs the test suite inside the image

FROM python:3.12-slim AS base

# git is vit's storage engine (>= 2.38 for `merge-tree --write-tree`; bookworm ships 2.39).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    # The workspace is a mounted volume, possibly owned by another uid.
    && git config --system --add safe.directory '*'

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIT_DEMO_WORKSPACE=/data

WORKDIR /app
COPY vit/ vit/
COPY demo/ demo/


# ── Test stage: `docker build --target test .` fails if any test fails ──────
FROM base AS test
RUN pip install --no-cache-dir pytest
COPY tests/ tests/
RUN python -m pytest tests/ -q


# ── Runtime stage (default) ─────────────────────────────────────────────────
FROM base AS runtime

RUN useradd --create-home --uid 10001 vit \
    && mkdir -p /data \
    && chown vit:vit /data
USER vit

VOLUME ["/data"]
EXPOSE 8765

# $PORT is honored by demo/server.py (falls back to 8765) so the same image
# works unchanged both locally (docker-compose, no $PORT set) and on a PaaS
# that injects its own port and routes to it (Render, Railway, Heroku, ...).
ENV PORT=8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c 'import os, urllib.request; urllib.request.urlopen("http://127.0.0.1:%s/api/state" % os.environ["PORT"], timeout=4)'

# Bind all interfaces inside the container; docker-compose publishes the port
# on the host's loopback only. --port is intentionally omitted so $PORT wins.
CMD ["python", "demo/server.py", "--host", "0.0.0.0", "--no-browser"]
