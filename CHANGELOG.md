# Changelog

All notable changes to mgi-link are documented here.

## [Unreleased]

## [0.5.4] - 2026-07-13

### Security

- Adopt the GeneFoundry router container-release standard with SHA-pinned
  reusable CI/release callers, typed release configuration, digest-only
  production Compose, complete OCI labels, and code-only image content policy.

## [0.5.3] - 2026-07-12

### Security

- Replaced the mutable uv installer bootstrap in the Docker builder with a
  digest-pinned image copy, so production builds are reproducible from the
  reviewed container digest. Research use only.

## [0.5.2] - 2026-07-11

### Security

- Guard FastMCP-core not-found reflection: an unknown tool name, unknown/malformed
  resource URI, or unknown prompt name is no longer reflected — neither the
  caller-supplied text nor its control/zero-width/bidi/NUL code points — into any
  caller-visible field (structured_content and the TextContent mirror), the JSON-RPC
  error frame, or any log record at any level. Adds a layered guard
  (`mgi_link/mcp/notfound_guard.py`): a registry preflight returning a fixed,
  name-free `not_found` envelope (`is_error=True`, no `_meta.tool` echo); a
  URI-free `on_read_resource` boundary; a protocol-handler backstop covering the
  unknown-tool return path and the unknown-prompt echo; and a marker-based
  validation-log scrub filter attached to FastMCP's own non-propagating handlers.
  Research use only. (Response-Envelope Standard v1.1, error-message-sanitation
  fast-follow; non-breaking — error content only.)

## [0.5.1] - 2026-07-11

### Security

- Defense in depth: caller-visible error messages and structured fields are built
  from fixed/validated values (no upstream/exception prose), sanitized of
  control/zero-width/bidi/NUL code points; the local DB path, upstream error text,
  and decode failures are no longer echoed or logged raw. Research use only.

## [0.5.0] - 2026-07-11

### Changed (BREAKING)

- Response-Envelope Standard v1.1 untrusted-content fencing: `get_mp_term`'s
  `/definition` and `search_phenotype_terms`' `/results/*/definition` — both
  externally sourced Mammalian Phenotype (MP) ontology prose — are now emitted
  as the typed `untrusted_text` object (`kind`/`text`/`provenance`/
  `raw_sha256`) instead of a bare string, so MCP hosts can never confuse
  retrieved ontology prose with instructions. This is a breaking reshape (no
  legacy string field is kept alongside the typed object); callers reading
  `definition` as a string must update to read `definition.text`.
- Added `mgi_link/mcp/untrusted_content.py` (the fleet's shared fencing
  primitive: `fence_untrusted_text`, `UntrustedText`, plus a v1.1 limits guard,
  `enforce_untrusted_text_limits`, that raises `UntrustedTextLimitError` on a
  ceiling breach rather than silently truncating).

### Added

- New typed error code `response_limit_exceeded` (non-retryable,
  `recovery_action: reformulate_input`): a v1.1 untrusted-text limit breach now
  surfaces as its own explicit execution error in the MCP envelope instead of a
  generic `internal_error`, and is listed in `get_server_capabilities`.

### Security

- Defense in depth: upstream MP-ontology definitions are typed as data at the
  MCP serialization boundary, closing off prompt-injection vectors carried in
  externally sourced free text. Research use only; not clinical decision
  support.

## [0.4.0] - 2026-07-10

### Security

- Enforce exact configurable Host and Origin allowlists across every HTTP
  route, with safe loopback defaults, wildcard rejection, explicit production
  proxy hosts, and native FastMCP protection in depth. FastMCP is upgraded to
  3.4.4 while preserving structured argument-validation error envelopes.

### Changed (BREAKING)

- Host and Origin admission is now default-deny outside the configured
  loopback values. Non-loopback and reverse-proxy deployments must list their
  exact public names in `MGI_LINK_ALLOWED_HOSTS` and browser origins, when
  used, in `MGI_LINK_ALLOWED_ORIGINS`.

## [0.3.3] - 2026-07-10

### Security

- Harden MGI and MouseMine acquisition with redirect rejection, configurable
  size and time limits, same-directory atomic replacement, and preservation of
  the previous valid report on transfer failure.

## [0.3.2] - 2026-07-07

### Security

- Disabled CORS credentials on this unauthenticated backend (it holds no
  cookies/session) and added a startup guard that rejects the
  credentials-with-wildcard-origin footgun.
- Redacted URL secrets (userinfo, query, fragment) before the MouseMine
  `base_url` is echoed in the `get_diagnostics` payload or written to the
  live-fallback log.
- Removed the personal maintainer email from the default MouseMine
  `User-Agent`; a non-personal project URL is advertised unless an operator
  explicitly configures a contact mailbox
  (`MGI_LINK_MOUSEMINE__CONTACT_EMAIL`).
- Stopped logging the absolute database path on startup/refresh and on the
  corrupt-db warning (it could expose local usernames / directory layout);
  the database filename is logged instead.

### Changed

- Per-call research-use disclaimer (`unsafe_for_clinical_use`) now emitted in
  `_meta` on every tool response, all response_modes, success and error paths
  (fleet Response-Envelope Standard v1 disclaimer standardization). Previously
  this restriction was declared only once, in `get_server_capabilities`.

## [0.3.1] - 2026-06-30

### Security (Container & Deployment Hardening Standard v1)

- Pinned the `python:3.12-slim` base image by digest, added a root
  `.dockerignore` (keeps the local `docker/.env` and caches out of image layers),
  added a `container-security` CI workflow (Trivy + CycloneDX SBOM), and brought
  the base `docker-compose.yml` to parity with the npm overlay (`read_only`
  rootfs + tmpfs scratch, `cap_drop: ALL`, `no-new-privileges`, `init`,
  pids/mem/cpu limits; the `mgi-data` volume remains the only writable mount).

## [0.3.0] - 2026-06-13

Adopt the **GeneFoundry Tool-Naming Standard v1** so the server composes cleanly
behind `genefoundry-router` (tools surface as `mgi_<tool>` at the gateway).

### Changed (BREAKING)

- Renamed the discovery tool `get_mgi_diagnostics` → **`get_diagnostics`**. The
  embedded `mgi` source token was redundant under the gateway's `mgi_` namespace
  prefix (it produced `mgi_get_mgi_diagnostics`). The gateway-qualified name is
  now `mgi_get_diagnostics`. The payload, behaviour, and the service method are
  unchanged; update any direct callers of the tool name.

### Added

- Tool-name compliance test (`tests/unit/test_tool_names.py`): every registered
  tool must match `^[a-z0-9_]{1,50}$`, start with a canonical verb
  (`get|search|list|resolve|find|compare|compute`), and not self-prefix the
  `mgi` namespace token.
- README documents the canonical gateway **namespace token** `mgi`.

### Fixed

- Reconciled the package version (`pyproject.toml` was `0.1.0`, `__init__.py` was
  `0.2.0`) to a single `0.3.0`.

## [0.2.0] - 2026-06-13

### Added

- **Optional live MouseMine (InterMine) cold-start fallback.** When the local
  index is unavailable and `MGI_LINK_MOUSEMINE__ENABLE_LIVE_FALLBACK=true`,
  `resolve_marker` and `get_marker` serve from a live MouseMine query (genes
  only); responses carry `_meta.source="mousemine"` and `get_marker` sets
  `_meta.partial`. All other tools return `data_unavailable` while cold. Default
  off — behaviour is unchanged.
- Uniform truncation contract (`{total, returned, limit, truncated}`) on list
  tools, deduplicated support-ordered phenotype term view, exact-match search
  boosting, `_meta.elapsed_ms`, and build provenance in diagnostics.

## [0.1.0] - 2026-06-12

Initial release. An MCP server grounding mouse-genetics work in MGI (Mouse Genome
Informatics), reproducing the gene/marker page — Mutations, Alleles, Phenotypes —
from a local SQLite index built from the MGI bulk reports.

### Added

- **Offline SQLite index** built from the MGI bulk data reports (MRK_List2,
  MGI_PhenotypicAllele, MGI_GenePheno, VOC_MammalianPhenotype, MPheno_OBO,
  HOM_MouseHumanSequence, MGI_DO, MRK_ENSEMBL): atomic build, conditional-GET
  refresh, `fcntl` build lock, MP ontology closure + top-level system derivation.
- **13 MCP tools**: `resolve_marker`, `get_marker`, `search_markers`,
  `get_marker_alleles` (with generation-method category counts),
  `get_marker_phenotypes`, `get_phenotype_overview` (the 27-system grid),
  `get_marker_diseases`, `get_marker_ortholog`, `get_mp_term`,
  `search_phenotype_terms`, `find_markers_by_phenotype`, plus
  `get_server_capabilities` and `get_mgi_diagnostics`.
- Human-gene → mouse-ortholog resolution (`match_type=ortholog`).
- Structured output schemas, `response_mode` verbosity, `_meta.next_commands`
  chaining, the 7-code error taxonomy, argument aliases + did-you-mean, and the
  `mgi://` discovery resources.
- `mgi-link-data` CLI (`build` / `refresh` / `status`), Docker image, and
  cron/systemd deployment docs.
- Unit + integration test suites (validated against the live MGI release for Wt1,
  MGI:98968).

### Notes

- Phenotype annotations are single-gene genotypes (MGI_GenePheno). Multigenic
  genotypes, IMSR strain availability, gene expression (GXD), and recombinase
  activity are out of scope in v1.
- A live MouseMine (InterMine) enrichment client is reserved for v2.
