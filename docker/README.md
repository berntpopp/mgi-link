# Docker

```bash
make docker-build       # build the image
make docker-up          # start (prints the MCP URL + Claude Code command)
make docker-logs        # follow logs
make docker-down        # stop
```

The one-shot `mgi-data-init` service restores the image's pinned, digest-verified
`data-mgi-*` data release (a GitHub release of this repository, ~89 MB gzip →
~390 MB SQLite) into the `mgi-data` volume and exits; the server then mounts that
volume **read-only**. Nothing is downloaded from MGI at boot and there is no
refresh service: a new data release arrives with a reviewed re-pin and a new
image. See [`../docs/deployment.md`](../docs/deployment.md#docker-pinned-data-release).

## Ports

The host port defaults to `8000`; override with `MGI_LINK_HOST_PORT` (e.g. in
`docker/.env`). MCP endpoint: `http://127.0.0.1:<port>/mcp`. Health:
`http://127.0.0.1:<port>/health`.
