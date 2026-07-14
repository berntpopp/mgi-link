# mgi-link

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/berntpopp/mgi-link/actions/workflows/ci.yml/badge.svg)](https://github.com/berntpopp/mgi-link/actions/workflows/ci.yml)
[![Conformance](https://github.com/berntpopp/mgi-link/actions/workflows/conformance.yml/badge.svg)](https://github.com/berntpopp/mgi-link/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An **MCP (Model Context Protocol)** server that grounds mouse-genetics work in
**Mouse Genome Informatics** ([informatics.jax.org](https://www.informatics.jax.org/)).
It reproduces the data on an MGI gene/marker page — especially **Mutations,
Alleles, and Phenotypes** — as structured tools an agent can call.

> [!IMPORTANT]
> Research use only. Not clinical decision support. Do not use for diagnosis,
> treatment, triage, or patient management.

## Why

The MGI gene page (e.g. [Wt1, MGI:98968](https://www.informatics.jax.org/marker/MGI:98968))
is a rich JS app with **no clean JSON API**. The data behind it exists only as
bulk TSV reports and an OBO ontology file — no endpoint answers "what phenotypes
does knocking out this gene cause?".

`mgi-link` rebuilds that surface from MGI's canonical bulk reports into a fast,
offline, deterministic SQLite index and exposes it as MCP tools with structured
outputs, `response_mode` verbosity control, and `_meta.next_commands` chaining.
It also closes the mouse↔human gap: pass a **human** symbol or HGNC id to any
marker tool and it resolves through the ortholog.

## Quick start

Hosted — no install:

```bash
claude mcp add --transport http mgi-link https://mgi-link.genefoundry.org/mcp
```

Locally (Python 3.12+, [uv](https://github.com/astral-sh/uv)). **`make data` is
required**: the server has no data until the MGI reports are downloaded and the
index is built.

```bash
make install      # uv sync --group dev
make data         # REQUIRED: download the MGI bulk reports, build the SQLite index
make dev          # unified server: FastAPI /health + MCP /mcp on 127.0.0.1:8000
make mcp-serve    # or: the stdio MCP server
```

```bash
claude mcp add mgi-link -- uv run mgi-link-mcp   # stdio
```

Deploying behind a reverse proxy? `MGI_LINK_ALLOWED_HOSTS` must list the public
hostname — see [configuration.md](docs/configuration.md).

## Tools

| Tool | Purpose |
|------|---------|
| `resolve_marker` | Resolve a mouse symbol / MGI id / **human ortholog** → canonical marker |
| `get_marker` | Full marker record: location, xrefs, ortholog, summary counts |
| `search_markers` | Full-text search over marker symbol / name / synonyms |
| `get_marker_alleles` | Mutations & Alleles + generation-method category counts |
| `get_marker_phenotypes` | MP annotations (allelic composition, background, PubMed) + summary |
| `get_phenotype_overview` | The 27-system MGI **Phenotype Overview** grid |
| `get_marker_diseases` | Human–mouse disease models (DO/OMIM) |
| `get_marker_ortholog` | Mouse ↔ human ortholog (HGNC/Entrez/Ensembl/OMIM) |
| `get_mp_term` | Mammalian Phenotype ontology term (parents/children/systems) |
| `search_phenotype_terms` | Full-text search over MP terms |
| `find_markers_by_phenotype` | Reverse lookup: MP term → mouse genes (descendants included) |
| `get_server_capabilities` | Discovery: the tool surface, vocabularies, limits, citation |
| `get_diagnostics` | Health and provenance: the loaded MGI release |

Leaf names are intentionally **unprefixed** per the GeneFoundry
[Tool-Naming Standard v1](https://github.com/berntpopp/genefoundry-router). The
canonical gateway namespace token is `mgi`: behind
[`genefoundry-router`](https://github.com/berntpopp/genefoundry-router) these
surface as `mgi_<tool>` (e.g. `mgi_get_marker`), with `get_marker_phenotypes`
pinned as the entry point. Worked call sequences: [usage.md](docs/usage.md).

## Data & provenance

The index is built from the MGI bulk reports at
[informatics.jax.org/downloads/reports](https://www.informatics.jax.org/downloads/reports/):
`MRK_List2`, `MGI_PhenotypicAllele`, `MGI_GenePheno`, `VOC_MammalianPhenotype`,
`MPheno_OBO.ontology`, `HOM_MouseHumanSequence`, `MGI_DO` and `MRK_ENSEMBL`. A
live MouseMine (InterMine) enrichment client exists but is off by default and
reserved for v2.

MGI publishes roughly weekly. `mgi-link-data refresh` is conditional (ETag /
Last-Modified, so an unchanged release costs one `304`) and is driven by an
**external cron job** — the in-process scheduler is off by default. Full model:
[data.md](docs/data.md).

**Data licence.** MGI data are freely available for research use; please cite MGI
/ The Jackson Laboratory ([copyright](https://www.informatics.jax.org/mgihome/other/copyright.shtml)).
The **Mammalian Phenotype Ontology is licensed CC BY 4.0**, a separate grant.

**Cite** (served verbatim at `mgi://citation`): Baldarelli RM, Smith CL, Bello SM,
et al. Mouse Genome Informatics: an integrated knowledgebase system for the
laboratory mouse. *Genetics*. 2024;227(1):iyae031. doi:10.1093/genetics/iyae031.
RRID:SCR_006460.

## Documentation

- [Usage](docs/usage.md) — canonical workflows, the tool reference, and what is out of scope in v1.
- [Configuration](docs/configuration.md) — every `MGI_LINK_*` variable, the entry points, and the Host/Origin allowlists.
- [Data](docs/data.md) — the source reports, the refresh model, licensing and citation.
- [Deployment](docs/deployment.md) — cron, systemd, Docker, and running behind a proxy.
- [Architecture](docs/architecture.md) — the data plane, the SQLite schema, and the MCP plane.
- [AGENTS.md](AGENTS.md) — engineering conventions and architecture invariants.

## Contributing

See [AGENTS.md](AGENTS.md) for engineering conventions and the invariants not to
break. `make ci-local` is the definition-of-done gate: format, lint, line budget,
README standard, mypy strict, and tests. It must be green before a change lands.

## License

Code: [MIT](LICENSE) © mgi-link contributors. Data: MGI data are free for
research use (cite MGI / The Jackson Laboratory); the Mammalian Phenotype
Ontology is CC BY 4.0.
