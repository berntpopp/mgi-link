# Configuration

All settings use the `MGI_LINK_` prefix; nested config uses a double underscore
(`MGI_LINK_DATA__DB_FILENAME`). Every key is optional — the defaults below are
what the server runs with. [`.env.example`](../.env.example) is the copy-paste
starting point; [`.env.docker.example`](../.env.docker.example) covers the
Nginx-Proxy-Manager deployment.

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
| `MGI_LINK_PORT` | `8000` | |
| `MGI_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio`. |
| `MGI_LINK_ALLOWED_HOSTS` | `["localhost","127.0.0.1","::1"]` | JSON list of **exact** Host values. |
| `MGI_LINK_ALLOWED_ORIGINS` | `[]` | JSON list of **exact** browser Origins. |
| `MGI_LINK_LOG_LEVEL` | `INFO` | |
| `MGI_LINK_LOG_FORMAT` | `console` | `console` \| `json`. |

### Host / Origin allowlists (read before deploying behind a proxy)

HTTP deployments enforce **exact** Host and Origin allowlists on every route.

- `MGI_LINK_ALLOWED_HOSTS` must be a JSON list containing the **public
  reverse-proxy hostname** in addition to the loopback defaults. A request whose
  `Host` header is not on the list is rejected — this is the DNS-rebinding
  guard, and it is the single most common cause of a working local server that
  404s or 400s once it is proxied.
- `MGI_LINK_ALLOWED_ORIGINS` defaults to `[]`, which **permits requests without
  an `Origin` header** (non-browser MCP clients such as Claude Code send none)
  while rejecting every browser origin. Add an origin only for a browser client.

## Local data store

| Variable | Default | Notes |
|----------|---------|-------|
| `MGI_LINK_DATA__DATA_DIR` | `./data` | Where `mgi.sqlite` and the downloaded reports live. |
| `MGI_LINK_DATA__REPORTS_BASE_URL` | `https://www.informatics.jax.org/downloads/reports` | Upstream bulk reports. |
| `MGI_LINK_DATA__AUTO_BOOTSTRAP` | `true` | Build the index on first start if absent. |
| `MGI_LINK_DATA__REFRESH_ENABLED` | `false` | In-process scheduler; **cron owns refresh by default**. |
| `MGI_LINK_DATA__REFRESH_INTERVAL_HOURS` | `168` | Only when the scheduler is enabled; MGI updates ~weekly. |

See [data.md](data.md) for the source reports and the refresh model.

## Live MouseMine enrichment (reserved for v2)

| Variable | Default | Notes |
|----------|---------|-------|
| `MGI_LINK_MOUSEMINE__ENABLE_LIVE_FALLBACK` | `false` | Off by default; reserved for v2. |
| `MGI_LINK_MOUSEMINE__CONTACT_EMAIL` | — | Sent to MouseMine when the fallback is enabled. |
| `MGI_LINK_MOUSEMINE__RATE_LIMIT_PER_S` | `2.0` | Politeness limit for the live client. |

## Response shaping

`response_mode` is a per-call argument, not an env var: `minimal | compact |
standard | full`, default **`compact`** (projected in `services/shaping.py`).
Every response carries `_meta.next_commands` — ready-to-call follow-up steps — on
success **and** on error. See [usage.md](usage.md).
