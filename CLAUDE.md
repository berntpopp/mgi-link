# CLAUDE.md

**Read `AGENTS.md` first** — it holds the engineering conventions and
architecture invariants for this project.

## TL;DR

`mgi-link` is an MCP server grounding mouse-genetics work in MGI (Mouse Genome
Informatics). It reproduces the MGI gene/marker page — Mutations, Alleles,
Phenotypes — from a local SQLite index built from the MGI bulk reports. Sibling
of `hgnc-link` / `gnomad-link` / `uniprot-link`; same offline-index architecture.

Invariants: services return plain dicts, the MCP layer owns the envelope; every
response has `_meta.next_commands`; the 7-code error taxonomy; every tool has an
`output_schema`; `response_mode` = minimal|compact|standard|full; 500-line file
budget; mypy strict; `make ci-local` green.

## Common commands

```bash
make install            # uv sync --group dev
make data               # download MGI reports + build the local SQLite index
make dev                # unified server (FastAPI /health + MCP /mcp)
make mcp-serve          # stdio MCP server
make test               # tests
make test-integration   # opt-in: validate Wt1 against a real build
make ci-local           # the definition-of-done gate
```

## Layout

```
mgi_link/
  config.py constants.py identifiers.py exceptions.py        # data-plane foundations
  data/        schema.sql repository.py                       # SQLite read layer
  ingest/      downloader.py parser.py builder.py cli.py lock.py
  services/    mgi_service.py shaping.py refresh.py
  mcp/         facade.py envelope.py next_commands.py middleware.py arg_help.py
               annotations.py schemas.py capabilities.py resources.py
               tools/ markers.py alleles.py phenotypes.py orthologs.py ontology.py discovery.py
```
