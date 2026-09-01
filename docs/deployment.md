# Deployment

`mgi-link` serves a local SQLite index built from the MGI bulk reports. The index
is refreshed by an **external cron job** (the in-process scheduler is OFF by
default — `MGI_LINK_DATA__REFRESH_ENABLED=false`).

## Build / refresh the index

```bash
mgi-link-data build     # force a full download + rebuild
mgi-link-data refresh   # conditional: rebuild only if a report changed (the cron command)
mgi-link-data status    # print provenance of the existing DB
```

`refresh` issues conditional GETs (ETag / Last-Modified), so when MGI hasn't
published a new release every report returns `304` and no rebuild happens. MGI
updates roughly weekly. See [data.md](data.md) for the source reports, the
primary-report rule, and the atomic-build guarantee.

The index is **required**: the server has no data until `build` has run once.

## Cron options

**Host crontab** (weekly, Monday 03:17):

```cron
17 3 * * 1  cd /opt/mgi-link && /usr/bin/env uv run mgi-link-data refresh >> /var/log/mgi-link-refresh.log 2>&1
```

**systemd timer** (recommended): a `mgi-link-refresh.service` (Type=oneshot,
`ExecStart=uv run mgi-link-data refresh`) plus a `mgi-link-refresh.timer`
(`OnCalendar=Mon *-*-* 03:17:00`, `RandomizedDelaySec=1800`).

**Docker** (one-shot refresh service under the `tools` profile):

```bash
docker compose -f docker/docker-compose.yml run --rm refresh
```

## Running the server

- **Unified** (FastAPI `/health` + MCP `/mcp` in one uvicorn process):
  `python server.py --transport unified` or `make dev`. Console script:
  `mgi-link`.
- **Stdio** (for Claude Desktop / `claude mcp add`): `mgi-link-mcp` or
  `make mcp-serve`.

Register the hosted deployment or a local HTTP server with Claude Code:

```bash
claude mcp add --transport http mgi-link https://mgi-link.genefoundry.org/mcp
claude mcp add --transport http mgi-link http://127.0.0.1:8000/mcp   # local
claude mcp add mgi-link -- uv run mgi-link-mcp                       # local, stdio
```

## Docker

```bash
make docker-build
make docker-up      # starts the unified server; entrypoint builds/refreshes the index first
make docker-logs
make docker-url     # prints the MCP URL + a `claude mcp add` line
```

The Dockerfile is multi-stage (`python:3.14-slim`, `uv sync --frozen --no-dev`),
runs as a non-root user, persists `/app/data` (the ~370 MB index) in the
`mgi-data` named volume, and has a `/health` healthcheck with a long
`start-period` to cover the first build. `entrypoint.sh` runs
`mgi-link-data refresh` before serving so the request path never triggers a lazy
build.

## Fleet deploy contract (strato_v6_docker_npm)

`docker/docker-compose.npm.yml` is the overlay the fleet controller repo
(`strato_v6_docker_npm`) actually deploys and validates — it pulls the
released, attested `ghcr.io/berntpopp/mgi-link` image at a pinned digest and
never builds from source. Every service in that file must declare a numeric
`user: "<uid>:<gid>"` (currently `999:999`, this image's own uid:gid from
`docker/Dockerfile`) because the controller's runtime observer proves the
effective uid from `/proc`. The release Compose files named in
`container-release.json` (`docker/docker-compose.yml`,
`docker/docker-compose.prod.yml`) must **not** declare `user` — the shared
release gate (`container_release.py validate-compose`) forbids it there.
`tests/unit/test_deploy_overlay_user.py` guards both rules.

Release checklist enforced by this repo: bump `pyproject.toml`, run `uv lock`,
add a `CHANGELOG.md` heading `## [x.y.z] - YYYY-MM-DD`, bump `CITATION.cff`
`version:` (generated file; `date-released` is regenerated externally by
`genefoundry-router`'s `make citation-write`, not by this repo's release),
tag `vx.y.z`, then approve the `release` environment gate:
`gh api repos/berntpopp/mgi-link/actions/runs/<id>/pending_deployments`
(`status: waiting` marks the gate; may need approving twice).

Self-check that the overlay still projects cleanly for the fleet controller:

```bash
MGI_LINK_IMAGE="ghcr.io/berntpopp/mgi-link@sha256:<64 hex>" docker compose -f docker/docker-compose.npm.yml config --format json > /tmp/r.json
# from strato_v6_docker_npm:
uv run python -c "import sys,json; sys.path.insert(0,'scripts'); from utils.deployment_preflight import canonical_projection; canonical_projection(json.load(open('/tmp/r.json')), project='mgi-link'); print('PROJECTION OK')"
```

## Configuration

All settings use the `MGI_LINK_` prefix; nested config uses `__`. The full
reference — every variable, its default, and the three console entry points — is
[configuration.md](configuration.md), whose exhaustiveness is enforced by a unit
test against the live settings model; `.env.example` is the copy-paste starting
point for the settings you are most likely to change.

### Behind a reverse proxy

HTTP deployments enforce **exact** Host and Origin allowlists on every route.
`MGI_LINK_ALLOWED_HOSTS` must be a JSON list carrying the **public
reverse-proxy hostname** alongside the loopback defaults, or the proxied server
will reject every request. `MGI_LINK_ALLOWED_ORIGINS` defaults to `[]`, which
still admits non-browser MCP clients (they send no `Origin` header); add an
origin only for a browser client. A **third**, separate list —
`MGI_LINK_CORS_ORIGINS`, which feeds the CORS middleware — does *not* default to
empty: it ships with the development origins `http://localhost:3000` and
`http://127.0.0.1:3000`. Set it to `[]` on a proxied deployment unless a browser
client needs to read responses. See
[configuration.md](configuration.md#host--origin-allowlists-read-before-deploying-behind-a-proxy).
