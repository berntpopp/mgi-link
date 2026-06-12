# AGENTS.md — engineering conventions for mgi-link

`mgi-link` is an MCP server grounding mouse-genetics work in the MGI (Mouse
Genome Informatics) dataset. It is a sibling of `hgnc-link` / `gnomad-link` /
`uniprot-link` / `gencc-link` and follows the same offline-SQLite-index
architecture. Read this before changing code.

## Golden rules

1. **`make ci-local` is the definition of done** (format-check, lint, 500-line
   budget, mypy strict, tests). It must be green before you call work complete.
2. **500-line budget per file** (`scripts/check_file_size.py`). Split a file
   that grows past it; large files are a smell that it does too much.
3. **mypy `strict` must pass** for `mgi_link`, `server.py`, `mcp_server.py`.
4. **stdout is sacred on stdio.** The MCP stdio transport speaks JSON-RPC on
   stdout; never `print()` to stdout in a code path the stdio server can hit.
   Logs go to stderr (`logging_config`). The ingest CLI may print (it is not the
   stdio server).

## Architecture invariants (do not break)

- **Two planes.** The *data plane* (`config`, `constants`, `data/`, `ingest/`,
  `services/`) builds and reads the local SQLite index. The *MCP plane*
  (`mcp/`) is domain-agnostic scaffolding shared with the sibling projects.
- **Services return plain dicts; the MCP layer owns the envelope.** A service
  method returns a shaped dict (or raises a typed exception). `run_mcp_tool`
  (`mcp/envelope.py`) injects `success` / `_meta` on success and converts any
  exception into a structured error dict — returned, never raised.
- **Every response carries `_meta.next_commands`** — a ready-to-call list of
  `{tool, arguments}` steps — on success AND error.
- **The 7-code error taxonomy** is fixed: `invalid_input`, `not_found`,
  `ambiguous_query`, `data_unavailable`, `rate_limited`, `upstream_unavailable`,
  `internal_error`. Add new conditions by mapping to one of these in
  `envelope._classify`, not by inventing codes.
- **Every tool declares `output_schema` + `READ_ONLY_OPEN_WORLD` annotations**,
  and its description's first sentence is the discovery summary, ending with a
  `Signature: tool(args...)` line.
- **`response_mode`** is `minimal | compact | standard | full` (default
  compact), projected in `services/shaping.py`.
- **Keep `capabilities.TOOLS` in sync** with the registered tools — a test
  asserts `set(TOOLS) == registered tool names`.
- **Identifiers** are normalised in `identifiers.py` (MGI:NNNN / bare NNNN /
  MP:NNNNNNN). Tools never parse ids by hand.

## Data plane

- The index is built from MGI bulk reports (`config.REPORT_FILENAMES`). The
  primary report (`genepheno`) drives conditional rebuilds.
- The build is **atomic** (`ingest/builder.build_database`: temp file +
  `os.replace`) under an `fcntl` `build_lock`, with `meta` provenance.
- `ingest/downloader` does conditional GET (ETag/Last-Modified) so a cron
  refresh is a cheap 304 when unchanged.
- The MP ontology closure (`mp_closure`) and the top-level systems
  (`mp_top_system`, direct children of `MP:0000001`) are derived from
  `MPheno_OBO.ontology` at build time — never hardcode MP system ids.
- Parsers (`ingest/parser.py`) are pure functions over file paths; column
  layouts are documented per report and verified against live data.

## Testing

- Unit tests build a **real** small SQLite index from the trimmed fixture
  reports in `tests/fixtures/` (no mocking of the DB layer); tools are exercised
  through the real FastMCP facade (`tests/unit/test_tools_e2e.py`).
- `respx` mocks the downloader. Coverage gate is 80% (`make test-cov`).
- `tests/integration/test_live.py` (opt-in, `make test-integration`) asserts the
  live pipeline reproduces the MGI page for Wt1 (MGI:98968); it skips unless a
  real `data/mgi.sqlite` exists.

## Adding a tool

1. Add the service method to `services/mgi_service.py` (returns a plain dict;
   raise typed exceptions for failures).
2. Add an `output_schema` in `mcp/schemas.py` and an `after_*` chain in
   `mcp/next_commands.py`.
3. Register the `@mcp.tool` in the right `mcp/tools/<area>.py` module (set the
   `_meta.next_commands`, wrap the body in `run_mcp_tool` with an
   `McpErrorContext`).
4. Add the tool name to `capabilities.TOOLS` and register the module in
   `mcp/facade.py` / `mcp/tools/__init__.py` if new.
5. Add tests (service + e2e through the facade). Run `make ci-local`.
