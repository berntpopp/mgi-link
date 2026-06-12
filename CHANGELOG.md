# Changelog

All notable changes to mgi-link are documented here.

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
