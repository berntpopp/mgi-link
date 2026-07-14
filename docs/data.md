# Data & provenance

`mgi-link` has **no data until the index is built**. `make data` (= `uv run
mgi-link-data build`) downloads the MGI bulk reports and builds the local SQLite
index; every tool returns a `data_unavailable` error until it has run once.

## Source reports

All reports are fetched from `https://www.informatics.jax.org/downloads/reports/`
(`MGI_LINK_DATA__REPORTS_BASE_URL`). The set is declared in
`mgi_link/config.py` (`REPORT_FILENAMES`):

| Report | Feeds |
|--------|-------|
| `MRK_List2.rpt` | markers: symbol, name, synonyms, type, location |
| `MGI_PhenotypicAllele.rpt` | alleles / mutations + generation method |
| `MGI_GenePheno.rpt` | gene → MP phenotype annotations (**primary report**) |
| `VOC_MammalianPhenotype.rpt` | the Mammalian Phenotype (MP) vocabulary |
| `MPheno_OBO.ontology` | MP ontology: closure, parents, top-level systems |
| `HOM_MouseHumanSequence.rpt` | mouse ↔ human orthologs (HGNC/Entrez/Ensembl/OMIM) |
| `MGI_DO.rpt` | human–mouse disease models (DO/OMIM) |
| `MRK_ENSEMBL.rpt` | Ensembl cross-references |

`MGI_GenePheno.rpt` is the **primary report**: its freshness drives a conditional
rebuild (`mgi_link/config.py`). The MP top-level systems (the Phenotype-Overview
grid columns) are derived from `MPheno_OBO.ontology` at build time — they are
never hardcoded.

## Refresh model

MGI publishes new reports roughly **weekly**. Refresh is owned by an **external
cron job**; the in-process scheduler is **off by default**
(`MGI_LINK_DATA__REFRESH_ENABLED=false`).

```bash
mgi-link-data build     # force a full download + rebuild
mgi-link-data refresh   # conditional rebuild — the cron command
mgi-link-data status    # print the provenance of the existing DB
```

`refresh` issues conditional GETs (ETag / Last-Modified), so when MGI has not
published a new release every report returns `304` and no rebuild happens. The
build is atomic (temp file + `os.replace`) under an `fcntl` lock, so a refresh
never exposes a half-written index to a running server. See
[deployment.md](deployment.md) for the crontab line, the systemd timer, and the
Docker one-shot refresh service.

`get_diagnostics` and `make data-status` both report the loaded MGI release, so a
consumer can tell which snapshot a number came from — counts reflect the current
release and may differ from an older gene-page snapshot.

## Live MouseMine enrichment (reserved for v2)

A live MouseMine (InterMine) client exists but is **disabled by default**
(`MGI_LINK_MOUSEMINE__ENABLE_LIVE_FALLBACK=false`) and reserved for v2. When
enabled it acts only as a fallback marker provider before the first index build
completes. `mgi-link` is a bulk-download-backed server, not a live-API proxy.

## Scope (v1)

Phenotype annotations are **single-gene genotypes** (`MGI_GenePheno`).
Multigenic-genotype phenotypes, IMSR strain availability, gene expression (GXD),
and recombinase activity are out of scope in v1.

## Licence and citation

MGI data are freely available for research use; please cite MGI / The Jackson
Laboratory (see the
[MGI copyright statement](https://www.informatics.jax.org/mgihome/other/copyright.shtml)).
The **Mammalian Phenotype Ontology is licensed CC BY 4.0** — a distinct grant
from MGI's general research-use terms.

The recommended citation is served verbatim at the `mgi://citation` resource and
in `get_server_capabilities` (`mgi_link/constants.py`):

> Baldarelli RM, Smith CL, Bello SM, et al. Mouse Genome Informatics: an
> integrated knowledgebase system for the laboratory mouse. Genetics.
> 2024;227(1):iyae031. doi:10.1093/genetics/iyae031. RRID:SCR_006460.
> Data: Mouse Genome Database (MGD), The Jackson Laboratory,
> https://www.informatics.jax.org/.

Research use only. Not clinical decision support.
