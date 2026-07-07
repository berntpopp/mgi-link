# Changelog

All notable changes to mgi-link are documented here.

## [Unreleased]

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
