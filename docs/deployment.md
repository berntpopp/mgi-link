# Deployment

`mgi-link` serves a local SQLite index built from the MGI bulk reports.
**Containers** (the fleet deploy) serve one pinned, digest-verified **data
release** restored at startup and never download from MGI (see "Docker" below).
The `build`/`refresh` CLI and cron options are for a **source checkout** only
(the in-process scheduler is OFF by default — `MGI_LINK_DATA__REFRESH_ENABLED=false`).

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

## Docker (pinned data release)

```bash
make docker-build
make docker-up      # mgi-data-init restores the pinned data release, then the server starts
make docker-logs
make docker-url     # prints the MCP URL + a `claude mcp add` line
```

- A one-shot **`mgi-data-init`** service runs `mgi-link-data materialize-data`
  before the server starts. It downloads the image's pinned `data-mgi-*` GitHub
  release asset of this repository (`github.com` /
  `release-assets.githubusercontent.com` only), verifies the compressed and
  expanded SHA-256 and the schema, writes `/data/<digest>/mgi.sqlite`, and
  atomically points `/data/current` at it. A restart re-verifies the existing
  snapshot without downloading.
- The **server mounts the volume read-only** and serves `/data/current/mgi.sqlite`;
  `/health` reports `release_identity.data_identity` (`expected` from the pin,
  `actual` re-proved from the served bytes; the ~390 MB hash is re-run only when
  the file changes). No in-app refresh, no upstream download.

### Data releases and re-pinning

`.github/workflows/data-release.yml` (weekly, or a manual dispatch on `main`)
downloads each report **once** and runs `mgi-link-data build --reproducible`
(`build_utc` pinned to the newest report `Last-Modified`, no build duration,
rollback journal, deterministic row order) and `mgi-link-data package`
(`mgi.sqlite.gz`, `manifest.json` with per-report validators + SHA-256,
`data-authorization.json`, `SHA256SUMS`) under the content-addressed tag
`data-mgi-<first 16 hex of the SQLite SHA-256>`; unchanged reports are a no-op.
A new tag waits on the `data-release` environment (owner review, `main` only),
is attested, digest-verified and published (never as the repository's "Latest").
Re-pin in one reviewed PR: `DATA_RELEASE_TAG`, `DATA_COMPRESSED_SHA256` and
`DATA_EXPANDED_SHA256` in `mgi_link/config.py` plus the same tag + `sha256:`
digest in `container-release.json` (`tests/unit/test_data_release_identity.py`
fails if they disagree), then release the app.

Licence: MGI data and the MP ontology are CC BY 4.0
([terms](https://www.informatics.jax.org/mgihome/other/copyright.shtml)); the
snapshot holds no images. `release/data-authorization.json` records the repository
owner's 2026-11-13 redistribution decision (the owner's determination, not an MGI
approval) and the attribution + change notice every release carries.

### Operator steps (fleet host)

1. Pull the released image by digest and set `MGI_LINK_IMAGE` as before.
2. `docker compose -f docker/docker-compose.npm.yml --env-file .env.docker up -d`.
   Compose starts `mgi-data-init` first (outbound HTTPS to `github.com` and
   `release-assets.githubusercontent.com`; ~0.5 GB free in the volume), waits for
   exit `0`, then starts the server. No manual staging is required.
3. Verify: `docker compose -f docker/docker-compose.npm.yml logs mgi-data-init`
   shows `Materialized MGI data release data-mgi-…`, and `/health`
   `release_identity` shows `expected == actual` with the tag/digest from
   `container-release.json`.
4. Optional cleanup: the old files in the existing `mgi-data` volume
   (`mgi.sqlite`, the `.rpt`/`.ontology` reports, `download_cache.json`,
   `.build.lock`) are no longer read and may be deleted (~600 MB); the restore
   writes only `<digest>/` and `current`.
5. Remove any host cron line that ran `docker compose ... run --rm refresh`; that
   service no longer exists.

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
