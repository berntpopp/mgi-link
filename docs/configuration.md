# Configuration

All settings use the `MGI_LINK_` prefix; nested config uses a double underscore
(`MGI_LINK_DATA__DB_FILENAME`). Every key is optional — the defaults below are
what the server runs with. [`.env.example`](../.env.example) is the copy-paste
starting point (the settings you are most likely to change);
[`.env.docker.example`](../.env.docker.example) covers the Nginx-Proxy-Manager
deployment.

The tables on this page are **exhaustive** and machine-checked:
`tests/unit/test_configuration_doc.py` enumerates the live settings model
(`mgi_link/config.py`) and fails if a variable exists in the model but not below.

## Entry points

Three console scripts are declared in `pyproject.toml`:

| Script | Purpose |
|--------|---------|
| `mgi-link` | the unified server — FastAPI `/health` + MCP `/mcp` in one process |
| `mgi-link-mcp` | the **stdio** MCP server (Claude Desktop, `claude mcp add`) |
| `mgi-link-data` | the data CLI — `build` / `refresh` / `status` |

`stdout` is reserved for the JSON-RPC protocol on stdio; logs go to stderr.

## Server

| Variable | Default | Notes |
|----------|---------|-------|
| `MGI_LINK_HOST` | `127.0.0.1` | Bind address. |
| `MGI_LINK_PORT` | `8000` | Range 1024–65535. |
| `MGI_LINK_RELOAD` | `false` | uvicorn auto-reload. Development only. |
| `MGI_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio`. |
| `MGI_LINK_MCP_PATH` | `/mcp` | MCP endpoint path; a leading `/` is added if missing. |
| `MGI_LINK_ALLOWED_HOSTS` | `["localhost","127.0.0.1","::1"]` | JSON list of **exact** Host values (wildcards rejected). |
| `MGI_LINK_ALLOWED_ORIGINS` | `[]` | JSON list of **exact** browser Origins. |
| `MGI_LINK_CORS_ORIGINS` | `["http://localhost:3000","http://127.0.0.1:3000"]` | JSON list of origins for the **CORS** middleware — see below. |
| `MGI_LINK_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`. |
| `MGI_LINK_LOG_FORMAT` | `console` | `console` \| `json`. |

### Host / Origin allowlists (read before deploying behind a proxy)

HTTP deployments enforce **exact** Host and Origin allowlists on every route.
There are **three** browser-facing knobs, and they are not the same thing:

- `MGI_LINK_ALLOWED_HOSTS` must be a JSON list containing the **public
  reverse-proxy hostname** in addition to the loopback defaults. A request whose
  `Host` header is not on the list is rejected — this is the DNS-rebinding
  guard, and it is the single most common cause of a working local server that
  404s or 400s once it is proxied.
- `MGI_LINK_ALLOWED_ORIGINS` defaults to `[]`, which **permits requests without
  an `Origin` header** (non-browser MCP clients such as Claude Code send none)
  while rejecting every browser origin. Add an origin only for a browser client.
- `MGI_LINK_CORS_ORIGINS` is a **separate** list, wired into Starlette's
  `CORSMiddleware` in `mgi_link/app.py`. It decides which browser origins a
  browser will let *read* a response, and it does **not** default to empty: it
  ships with the development origins `http://localhost:3000` and
  `http://127.0.0.1:3000`. On a proxied deployment set it to `[]` (or to the one
  browser origin you serve). `allow_credentials` is hard-coded `False` — the
  backend holds no cookie or session — and a startup guard refuses the
  wildcard-`*`-with-credentials combination outright.

## Local data store

| Variable | Default | Notes |
|----------|---------|-------|
| `MGI_LINK_DATA__DATA_DIR` | `./data` | Where `mgi.sqlite` and the downloaded reports live. |
| `MGI_LINK_DATA__DB_FILENAME` | `mgi.sqlite` | SQLite filename inside `DATA_DIR`. |
| `MGI_LINK_DATA__REPORTS_BASE_URL` | `https://www.informatics.jax.org/downloads/reports` | Upstream bulk reports. |
| `MGI_LINK_DATA__AUTO_BOOTSTRAP` | `true` | Build the index on first start if absent. |
| `MGI_LINK_DATA__REFRESH_ENABLED` | `false` | In-process scheduler; **cron owns refresh by default**. |
| `MGI_LINK_DATA__REFRESH_INTERVAL_HOURS` | `168` | Only when the scheduler is enabled; MGI updates ~weekly. Range 1–720. |
| `MGI_LINK_DATA__REFRESH_JITTER_SECONDS` | `600` | Random jitter per refresh (anti-thundering-herd). Range 0–86400. |
| `MGI_LINK_DATA__BUILD_LOCK_TIMEOUT` | `900` | Seconds to wait for the cross-process build lock. Range 1–7200. |
| `MGI_LINK_DATA__DOWNLOAD_TIMEOUT` | `300` | HTTP timeout (s) per bulk report. Range 5–1800. |
| `MGI_LINK_DATA__MAX_DOWNLOAD_BYTES` | `1073741824` | 1 GiB cap per report (largest measured < 512 MiB). |
| `MGI_LINK_DATA__MAX_DOWNLOAD_SECONDS` | `1800` | Elapsed-time cap while streaming one report. |
| `MGI_LINK_DATA__USER_AGENT` | `mgi-link/<version> (+https://github.com/berntpopp/mgi-link)` | Sent to `informatics.jax.org`. |
| `MGI_LINK_DATA__CACHE_SIZE` | `1024` | In-process query-cache entries; `0` disables. Range 0–65536. |
| `MGI_LINK_DATA__CACHE_TTL` | `3600` | Query-cache TTL (s). Range 0–86400. |

See [data.md](data.md) for the source reports and the refresh model.

## Live MouseMine enrichment (reserved for v2)

| Variable | Default | Notes |
|----------|---------|-------|
| `MGI_LINK_MOUSEMINE__ENABLE_LIVE_FALLBACK` | `false` | Off by default; reserved for v2. Nothing below has any effect while it is off. |
| `MGI_LINK_MOUSEMINE__BASE_URL` | `https://www.mousemine.org/mousemine/service` | InterMine web-service endpoint. |
| `MGI_LINK_MOUSEMINE__CONTACT_EMAIL` | *(empty)* | Optional operator mailbox in the outbound User-Agent; empty advertises the project URL instead. |
| `MGI_LINK_MOUSEMINE__TIMEOUT` | `30` | Per-request timeout (s). Range 1–120. |
| `MGI_LINK_MOUSEMINE__RATE_LIMIT_PER_S` | `2.0` | Politeness limit for the live client. Range 0.1–10. |
| `MGI_LINK_MOUSEMINE__MAX_RETRIES` | `2` | Retries on transient 429/5xx/network failures. Range 0–6. |

## Response shaping

`response_mode` is a per-call argument, not an env var: `minimal | compact |
standard | full`, default **`compact`** (projected in `services/shaping.py`).
Every response carries `_meta.next_commands` — ready-to-call follow-up steps — on
success **and** on error. See [usage.md](usage.md).
