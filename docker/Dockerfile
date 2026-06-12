# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for mgi-link.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /home/app/web
COPY uv.lock pyproject.toml README.md ./

RUN pip install --upgrade pip uv && \
    uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    MGI_LINK_HOST=0.0.0.0 \
    MGI_LINK_PORT=8000 \
    MGI_LINK_TRANSPORT=unified \
    MGI_LINK_MCP_PATH=/mcp \
    MGI_LINK_DATA__DATA_DIR=/app/data \
    # The entrypoint builds the index before the server starts. Refresh is owned
    # by cron (see docs/deployment.md), so the in-app scheduler stays OFF.
    MGI_LINK_DATA__AUTO_BOOTSTRAP=true \
    MGI_LINK_DATA__REFRESH_ENABLED=false \
    TMPDIR=/tmp/mgi-link

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /tmp/mgi-link /app/data && \
    chown -R app:app /tmp/mgi-link /app/data /home/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /home/app/web

COPY --chown=app:app ./mgi_link ./mgi_link
COPY --chown=app:app ./server.py ./mcp_server.py ./pyproject.toml ./README.md ./
COPY --chown=app:app ./docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN /opt/venv/bin/pip install . --no-deps && chmod +x /usr/local/bin/entrypoint.sh

# Stamp build provenance so get_server_capabilities/_meta can report which build
# answered. Pass at build time, e.g.:
#   docker build --build-arg MGI_LINK_GIT_SHA=$(git rev-parse --short HEAD) \
#                --build-arg MGI_LINK_BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ) .
ARG MGI_LINK_GIT_SHA=unknown
ARG MGI_LINK_BUILT_AT
ENV MGI_LINK_GIT_SHA=${MGI_LINK_GIT_SHA} \
    MGI_LINK_BUILT_AT=${MGI_LINK_BUILT_AT}

USER app

EXPOSE 8000

# The built SQLite index lives under MGI_LINK_DATA__DATA_DIR (/app/data).
# Mount a volume there so the ~73MB index persists across container restarts.
VOLUME ["/app/data"]

# start-period covers the entrypoint's first build (download ~33MB + ~4s build).
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=120s \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
