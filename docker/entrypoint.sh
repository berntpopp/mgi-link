#!/usr/bin/env bash
# Build the local MGI index before serving so the request path never triggers
# a lazy build, then start the server. Refresh is handled by cron (see
# docs/deployment.md), not the in-app scheduler.
set -euo pipefail

echo "[entrypoint] Ensuring the local MGI index is built/refreshed..."
if mgi-link-data refresh; then
    echo "[entrypoint] MGI index ready."
else
    echo "[entrypoint] WARN: build/refresh failed; the server will lazy-bootstrap on first use."
fi

exec python server.py \
    --transport "${MGI_LINK_TRANSPORT:-unified}" \
    --host "${MGI_LINK_HOST:-0.0.0.0}" \
    --port "${MGI_LINK_PORT:-8000}"
