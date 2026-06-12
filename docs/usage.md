# Usage

`mgi-link` reproduces the MGI gene/marker page for LLM agents. Start from
`resolve_marker`, then follow `_meta.next_commands`.

## Canonical workflows

**Mouse gene → the gene page**

```
resolve_marker(query="Wt1")            # or "MGI:98968", or a synonym
get_marker(query="MGI:98968")          # record + ortholog + summary counts
get_marker_alleles(query="MGI:98968")  # Mutations & Alleles + category counts
get_marker_phenotypes(query="MGI:98968")     # MP annotations + phenotype summary
get_phenotype_overview(query="MGI:98968")     # the 27-system grid
get_marker_diseases(query="MGI:98968")        # human-mouse disease models
get_marker_ortholog(query="MGI:98968")        # mouse↔human (HGNC/Entrez/Ensembl/OMIM)
```

**Human gene → mouse model.** Pass a human symbol or HGNC id to any
marker tool; it resolves through the ortholog (`match_type=ortholog`):

```
resolve_marker(query="WT1")            # or "HGNC:12796"
get_marker_phenotypes(query="HGNC:12796")
```

**Phenotype → genes (reverse).**

```
search_phenotype_terms(query="small kidney")     # → MP ids
get_mp_term(mp_id="MP:0002135")                   # term + parents/children/systems
find_markers_by_phenotype(mp_id="MP:0005367")     # every mouse gene with a renal/urinary phenotype
                                                  # (include_descendants=true by default)
```

## Tool reference

- `resolve_marker(query, response_mode=)` — symbol / MGI id / human ortholog →
  canonical marker, with `match_type`.
- `get_marker(query, response_mode=)` — full record + ortholog + summary counts.
- `search_markers(query, marker_type=, limit=, response_mode=)` — FTS over
  symbol/name/synonyms.
- `get_marker_alleles(query, allele_type=, limit=, response_mode=)` — alleles +
  generation-method `category_counts` (`allele_type` accepts friendly tokens like
  `knockout`, `crispr`).
- `get_marker_phenotypes(query, mp_system=, limit=, response_mode=)` — MP
  annotations + summary; `mp_system` filters to one top-level system.
- `get_phenotype_overview(query)` — the system grid (terms rolled up via the MP
  ontology).
- `get_marker_diseases(query)` — DO/OMIM disease models.
- `get_marker_ortholog(query, response_mode=)` — mouse↔human cross-references.
- `get_mp_term(mp_id)` / `search_phenotype_terms(query, limit=)` — MP ontology.
- `find_markers_by_phenotype(mp_id, include_descendants=, limit=)` — reverse
  lookup.
- `get_server_capabilities(detail=)` / `get_mgi_diagnostics()` — discovery.

## Notes

- Every response carries `_meta.next_commands`; follow the first entry to advance
  without guessing the next tool.
- `response_mode` is `minimal | compact | standard | full` (default compact).
- Phenotype annotations are **single-gene genotypes** (MGI_GenePheno).
  Multigenic-genotype phenotypes, IMSR strain availability, gene expression
  (GXD), and recombinase activity are out of scope in v1.
- Counts reflect the current MGI release (see `get_mgi_diagnostics`), which may
  differ from an older gene-page snapshot.
- Research use only; not for clinical decision support.
