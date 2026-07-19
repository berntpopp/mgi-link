# mgi-link — Design Spec

**Date:** 2026-06-12
**Status:** Approved (autonomous goal-driven build)
> Historical record

**Author:** Claude (MCP engineering)

## 1. Purpose

`mgi-link` is a Model Context Protocol (MCP) server that grounds mouse-genetics
questions in **Mouse Genome Informatics (MGI / informatics.jax.org)** data. It
reproduces the data on an MGI gene/marker page (e.g.
<https://www.informatics.jax.org/marker/MGI:98968> = *Wt1*) for LLM agents — with
priority on **Mutations, Alleles, and Phenotypes**:

- Marker record (symbol, name, type, GRCm39 location, synonyms, xrefs).
- **Alleles / Mutations**: per-allele detail + category counts (Targeted,
  Endonuclease-mediated, Radiation induced, Chemically induced, Transgenic, …).
- **Phenotypes**: MP annotations with allelic composition, genetic background,
  PubMed; phenotype-summary counts; the 27-system **Phenotype Overview** grid.
- **Human–mouse disease** models (DO/OMIM) and **orthologs** (mouse↔human
  HGNC/Entrez/Ensembl/OMIM).
- Reverse research lookups: **MP term → markers**, human gene → mouse ortholog.

It is a sibling of `hgnc-link`, `gnomad-link`, `uniprot-link`, `gencc-link` and
follows their architecture exactly. Research use only; not clinical decision
support.

## 2. Architecture

Clone of the **hgnc-link offline-SQLite-index archetype**. Two data sources:

1. **Offline SQLite index** (primary, deterministic, fast) built from MGI bulk
   `.rpt` reports, refreshed weekly by cron. Powers all core tools.
2. **Live MouseMine InterMine API** (optional enrichment / fresh fallback) for
   data not in the bulk reports or when fresher detail is wanted. Disabled by
   default; behind a config flag. Alliance Genome API reserved for future
   variant/HGVS enrichment.

```
mgi_link/
  config.py constants.py identifiers.py exceptions.py buildinfo.py
  logging_config.py app.py server_manager.py
  data/        schema.sql  __init__.py  repository.py        # SQLite read layer
  ingest/      downloader.py parser.py builder.py lock.py cli.py
  services/    mgi_service.py shaping.py refresh.py
  api/         mousemine.py        # optional live InterMine client (enrichment)
  mcp/         facade.py envelope.py next_commands.py middleware.py arg_help.py
               annotations.py schemas.py capabilities.py resources.py
               service_adapters.py
               tools/ _common.py discovery.py markers.py alleles.py
                      phenotypes.py orthologs.py ontology.py
```

The **MCP plane** (`envelope`, `next_commands`, `middleware`, `arg_help`,
`annotations`, `shaping`, `service_adapters`, `facade` skeleton) is copied
near-verbatim from hgnc-link (domain-agnostic). Only the data plane + tools are
MGI-specific. Invariants preserved: services return plain dicts; the MCP layer
owns the envelope; every response carries `_meta.next_commands` (success AND
error); 7-code error taxonomy (`invalid_input`, `not_found`, `ambiguous_query`,
`data_unavailable`, `rate_limited`, `upstream_unavailable`, `internal_error`);
every tool declares `output_schema` + `READ_ONLY_OPEN_WORLD`; `response_mode`
(minimal|compact|standard|full).

## 3. Data model (SQLite schema)

- `marker` — one row per mouse marker: `mgi_id` PK, symbol, symbol_upper, name,
  marker_type, feature_type, chromosome, cm_position, coord_start, coord_end,
  strand, status, synonyms (JSON), refseq, ensembl_gene_id, entrez_id (xrefs
  joined from MGI_PhenotypicAllele/MRK_ENSEMBL/HOM).
- `marker_lookup` — exploded `(lookup_symbol, mgi_id, symbol_type)` for
  resolution (current | synonym).
- `marker_fts` — FTS5 over symbol/name/synonyms.
- `allele` — `allele_id` PK, symbol, name, allele_type, attributes (JSON),
  pubmed_ids (JSON), marker_id, marker_symbol.
- `genopheno` — gene→phenotype annotation rows: marker_id, allele_ids (JSON),
  allelic_composition, allele_symbols, genetic_background, mp_id, pubmed_id,
  genotype_id. (from MGI_GenePheno.rpt)
- `mp_term` — `mp_id` PK, name, definition (VOC_MammalianPhenotype.rpt).
- `mp_closure` — `(mp_id, ancestor_id)` transitive ancestor pairs from
  MPheno_OBO, used to roll annotations up to the ~27 top-level systems.
- `mp_top_system` — the curated top-level MP system list (the Phenotype Overview
  grid categories) with display order.
- `ortholog` — marker_id → human symbol, human_entrez, hgnc_id, omim_gene_id,
  human_ensembl, human_coords (HOM_MouseHumanSequence.rpt). Reverse index on
  human symbol/HGNC.
- `disease_model` — marker_id → doid, disease_name, omim_ids (MGI_DO.rpt).
- `xref` — reverse external-id → mgi_id (entrez, ensembl, hgnc, …).
- `meta` — build provenance (release date, source URLs/etags, row counts,
  build_utc, duration).

## 4. Tools (v1)

Discovery: `get_server_capabilities`, `get_mgi_diagnostics`.

Core (mirror the gene page):
1. `resolve_marker(query, organism_aware)` — MGI id / mouse symbol / synonym /
   human symbol → canonical `{mgi_id, symbol, name, marker_type}`; surfaces
   ambiguity; resolves human symbol via ortholog. (like hgnc resolve_symbol)
2. `get_marker(query, response_mode)` — full marker record incl. location,
   xrefs, human ortholog, summary counts (alleles, phenotypes, diseases).
3. `search_markers(query, marker_type, limit)` — FTS over symbol/name/synonym.
4. `get_marker_alleles(query, allele_type, response_mode, limit)` — alleles +
   category counts (reproduces the "All Mutations and Alleles" panel).
5. `get_marker_phenotypes(query, mp_system, response_mode, limit)` — MP
   annotations with allelic composition / background / PubMed; phenotype summary
   counts (N phenotypes from M alleles in K backgrounds).
6. `get_phenotype_overview(query)` — the 27-system grid: which top-level MP
   systems are annotated for the marker, with per-system term lists (rolled up
   via mp_closure). Reproduces the Phenotype Overview matrix.
7. `get_marker_diseases(query)` — human-mouse disease models (DO/OMIM).
8. `get_marker_ortholog(query)` — mouse↔human ortholog + xrefs; also accepts a
   human symbol/HGNC id to go human→mouse.
9. `get_mp_term(mp_id)` — MP ontology term (id, name, definition, parents,
   children, top-level system).
10. `search_phenotype_terms(query, limit)` — MP term FTS.
11. `find_markers_by_phenotype(mp_id, include_descendants, limit)` — reverse:
    MP term → mouse markers annotated with it (descendants included).

Optional live (behind `enable_mousemine`, off by default): the same tools can
fall back to MouseMine when the index is cold; a `get_marker_expression` (GXD)
stretch tool is deferred to v2.

MCP resources: `mgi://capabilities`, `mgi://tools`, `mgi://usage`,
`mgi://reference`, `mgi://research-use`, `mgi://citation`.

## 5. Ingest pipeline

`mgi-link-data {build|refresh|status}` (typer CLI, the cron entry). Conditional
GET (ETag/Last-Modified) per report into `data/`; atomic SQLite build (tmp +
`os.replace`) under an `fcntl` lock; `meta` provenance row. Reports downloaded:
MRK_List2, MGI_PhenotypicAllele, MGI_GenePheno, VOC_MammalianPhenotype,
MPheno_OBO.ontology, HOM_MouseHumanSequence, MGI_DO. (HMD_HumanPhenotype and
MRK_ENSEMBL optional supplements.) Parser handles `#`-comment headers, the
`Sym<allele>` superscript convention, pipe/comma multi-value fields.

## 6. Testing

pytest unit + integration, `asyncio_mode=auto`. Session-scoped fixture builds a
**real** small SQLite index from trimmed fixture `.rpt` slices (Wt1 + a couple
markers) — no mocking of the DB layer. Tools tested through the real FastMCP
facade asserting the full envelope contract (next_commands, response_mode
projection, error shapes). `respx` mocks the downloader / MouseMine client.
Coverage gate 85%. Integration test (opt-in) hits a real partial build + asserts
Wt1/MGI:98968 reproduces the page's allele categories and phenotype systems.

## 7. Config (env prefix `MGI_LINK_`)

Server: HOST, PORT, TRANSPORT, MCP_PATH, LOG_LEVEL, LOG_FORMAT.
Data (`DATA__`): DATA_DIR, DB_FILENAME, REPORTS_BASE_URL, per-report filenames,
DOWNLOAD_TIMEOUT, USER_AGENT, AUTO_BOOTSTRAP, REFRESH_ENABLED,
REFRESH_INTERVAL_HOURS, BUILD_LOCK_TIMEOUT, CACHE_SIZE.
MouseMine (`MOUSEMINE__`): BASE_URL, ENABLE_LIVE_FALLBACK (false), TIMEOUT,
RATE_LIMIT_PER_S (2.0), MAX_RETRIES.

## 8. Out of scope (v1)

IMSR strain availability (link out), GXD gene-expression detail, recombinase
activity, Alliance HGVS variant enrichment, multigenic-genotype phenotypes from
MGI_PhenoGenoMP (GenePheno covers single-gene). These are v2 candidates.
