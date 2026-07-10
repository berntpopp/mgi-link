# mgi-link

An MCP (Model Context Protocol) / API server that grounds **mouse-genetics**
work in **Mouse Genome Informatics (MGI, [informatics.jax.org](https://www.informatics.jax.org/))**.
It reproduces the data on an MGI gene/marker page — especially **Mutations,
Alleles, and Phenotypes** — for LLM agents.

`mgi-link` is a sibling of `hgnc-link`, `gnomad-link`, `uniprot-link`, and
`gencc-link` and shares their architecture: a local SQLite index built from the
MGI bulk reports, refreshed by cron, served over a structured MCP surface.

## Why

The MGI gene page (e.g. [Wt1, MGI:98968](https://www.informatics.jax.org/marker/MGI:98968))
is a rich JS app with no clean JSON API. `mgi-link` rebuilds that surface from
MGI's canonical bulk data reports into a fast, offline, deterministic index and
exposes it as MCP tools with structured outputs, response-mode verbosity
control, and `_meta.next_commands` chaining.

## Tools

| Tool | Purpose |
|------|---------|
| `resolve_marker` | Resolve a mouse symbol / MGI id / **human ortholog** → canonical marker |
| `get_marker` | Full marker record: location, xrefs, ortholog, summary counts |
| `search_markers` | FTS over marker symbol / name / synonyms |
| `get_marker_alleles` | Mutations & Alleles + generation-method **category counts** |
| `get_marker_phenotypes` | MP annotations (allelic composition, background, PubMed) + summary |
| `get_phenotype_overview` | The 27-system **Phenotype Overview** grid |
| `get_marker_diseases` | Human-mouse disease models (DO/OMIM) |
| `get_marker_ortholog` | Mouse ↔ human ortholog (HGNC/Entrez/Ensembl/OMIM) |
| `get_mp_term` | Mammalian Phenotype ontology term (parents/children/systems) |
| `search_phenotype_terms` | FTS over MP terms |
| `find_markers_by_phenotype` | Reverse: MP term → mouse genes (descendants included) |
| `get_server_capabilities`, `get_diagnostics` | Discovery |

**Federation:** leaf tool names are intentionally unprefixed per the GeneFoundry
Tool-Naming Standard v1. The canonical gateway **namespace token** is `mgi`; when
federated behind `genefoundry-router`, tools surface as `mgi_<tool>` (e.g.
`mgi_get_marker`, `mgi_get_diagnostics`).

## Data sources

The local index is built from the MGI bulk reports at
`https://www.informatics.jax.org/downloads/reports/`:
`MRK_List2`, `MGI_PhenotypicAllele`, `MGI_GenePheno`, `VOC_MammalianPhenotype`,
`MPheno_OBO.ontology`, `HOM_MouseHumanSequence`, `MGI_DO` (+ `MRK_ENSEMBL`).
A live MouseMine (InterMine) enrichment client is reserved for v2.

## Quick start

```bash
make install      # uv sync --group dev
make data         # download the MGI reports and build the local SQLite index
make dev          # run the unified server (FastAPI /health + MCP /mcp)
make mcp-serve    # run the stdio MCP server
make test         # run the test suite
```

HTTP deployments enforce exact Host and Origin allowlists. Configure
`MGI_LINK_ALLOWED_HOSTS` as a JSON list containing the public reverse-proxy
hostname in addition to loopback defaults; `MGI_LINK_ALLOWED_ORIGINS` defaults
to `[]`, which permits requests without an `Origin` header.

Register with Claude:

```bash
claude mcp add mgi-link -- uv run mgi-link-mcp
```

## Data & license

MGI data are freely available for research use; please cite MGI / The Jackson
Laboratory. The Mammalian Phenotype Ontology is licensed CC BY 4.0.
**Research use only; not for clinical decision support, diagnosis, treatment, or
patient management.**

## Development

`make ci-local` is the definition-of-done gate (format-check, lint, 500-line
budget, mypy strict, tests). See `AGENTS.md` for engineering conventions and
`docs/` for architecture and deployment.
