# Architecture

`mgi-link` is an offline-index MCP server: it builds a local SQLite database from
the MGI bulk data reports and serves it over a structured MCP surface. It has two
planes.

## Data plane

```
MGI bulk reports (informatics.jax.org/downloads/reports/)
        |  ingest/downloader.py   (conditional GET, ETag/Last-Modified)
        v
   data/*.rpt + MPheno_OBO.ontology
        |  ingest/parser.py       (pure TSV/OBO parsers)
        v
   ingest/builder.py              (atomic build: temp file + os.replace, under fcntl lock)
        v
   data/mgi.sqlite                (read-only, WAL)
        |  data/repository.py     (read-only query layer)
        v
   services/mgi_service.py        (orchestration -> plain dicts; services/shaping.py projects response_mode)
```

### SQLite schema (`data/schema.sql`)

| Table | Source report | Purpose |
|-------|---------------|---------|
| `marker` | MRK_List2 (+MRK_ENSEMBL, HOM entrez) | one row per mouse marker + xrefs |
| `marker_lookup` | derived | exploded symbol/synonym → mgi_id resolver |
| `marker_fts` | derived | FTS5 over symbol/name/synonyms |
| `xref` | HOM, MRK_ENSEMBL | reverse external-id → mgi_id (entrez/ensembl/hgnc/omim/human_symbol) |
| `allele` | MGI_PhenotypicAllele | alleles/mutations + generation method |
| `genopheno` | MGI_GenePheno | gene→MP annotations (allelic composition, background, PubMed) |
| `mp_term` / `mp_fts` | VOC_MammalianPhenotype | MP vocabulary + FTS |
| `mp_closure` | MPheno_OBO | transitive ancestor pairs (roll annotations up to systems) |
| `mp_parent` | MPheno_OBO | direct is_a edges (term navigation) |
| `mp_top_system` | MPheno_OBO | the 27-ish Phenotype-Overview grid columns (direct children of MP:0000001) |
| `ortholog` | HOM_MouseHumanSequence | mouse↔human (HGNC/Entrez/Ensembl/OMIM/coords) |
| `disease_model` | MGI_DO | human-mouse disease models (DO/OMIM) |
| `meta` | — | one-row build provenance |

The full index (June 2026 build) is ~367 MB: ~657k markers, ~129k alleles, ~282k
phenotype annotations, ~15k MP terms, ~22k orthologs, ~4.4k disease models;
builds in under 10 s from downloaded reports.

## MCP plane (`mcp/`)

Domain-agnostic scaffolding shared with the sibling `*-link` servers:

- `facade.py` — builds the `FastMCP` instance, registers tools + resources +
  the arg-validation middleware.
- `envelope.py` — the boundary: `run_mcp_tool` injects `success`/`_meta` and maps
  exceptions to the 7-code error taxonomy.
- `next_commands.py` — per-tool `after_*` builders for `_meta.next_commands`.
- `middleware.py` + `arg_help.py` — argument aliases, did-you-mean, structured
  arg-binding errors.
- `schemas.py` — permissive `output_schema` per tool.
- `capabilities.py` + `resources.py` — the discovery surface and the `mgi://`
  resources.
- `tools/` — one module per tool group (markers, alleles, phenotypes,
  orthologs, ontology, discovery).

## Request flow

`call_tool` → middleware (alias rewrite / arg validation) → tool body →
`get_mgi_service()` → repository → SQLite. The tool sets
`_meta.next_commands`; `run_mcp_tool` injects `success`, `tool`, `request_id`,
and (on error) the structured envelope.
