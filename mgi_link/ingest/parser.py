"""Parse the MGI bulk reports into normalized rows and the MP ontology graph.

MGI reports are tab-delimited. Some carry a single header row (MRK_List2,
HOM_MouseHumanSequence, MGI_DO), some a ``#``-comment header block
(MGI_PhenotypicAllele), and some neither (MGI_GenePheno, VOC_MammalianPhenotype,
MRK_ENSEMBL). ``MPheno_OBO.ontology`` is OBO format. Allele symbols use the
``Sym<allele>`` superscript convention, preserved verbatim.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from mgi_link.constants import HUMAN_TAXON_ID, MOUSE_TAXON_ID, MP_ROOT

csv.field_size_limit(1 << 24)


def _read_tsv(path: Path, *, skip_header: bool) -> Iterator[list[str]]:
    """Yield tab-split rows from a report, skipping ``#`` comments / blank lines."""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        first = True
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            if first and skip_header:
                first = False
                continue
            first = False
            yield line.rstrip("\n").split("\t")


def _col(row: list[str], idx: int) -> str | None:
    """Return a trimmed column value, or ``None`` when empty/out of range."""
    if idx >= len(row):
        return None
    text = row[idx].strip()
    return text or None


def _split(value: str | None, *, seps: str = "|,") -> list[str]:
    """Split a multi-value cell on any of ``seps`` into a clean, de-duped list."""
    if not value:
        return []
    items = [value]
    for sep in seps:
        items = [piece for token in items for piece in token.split(sep)]
    out: list[str] = []
    for item in items:
        token = item.strip()
        if token and token not in out:
            out.append(token)
    return out


# -- markers (MRK_List2.rpt) ---------------------------------------------------


def iter_markers(path: Path) -> Iterator[dict[str, Any]]:
    """Yield marker records from MRK_List2.rpt (has a header row).

    Columns: MGI id, Chr, cM Position, coord start, coord end, strand, Symbol,
    Status, Name, Marker Type, Feature Type, Synonyms (pipe-separated).
    """
    for row in _read_tsv(path, skip_header=True):
        mgi_id = _col(row, 0)
        symbol = _col(row, 6)
        if not mgi_id or not symbol:
            continue
        yield {
            "mgi_id": mgi_id,
            "chromosome": _col(row, 1),
            "cm_position": _col(row, 2),
            "coord_start": _col(row, 3),
            "coord_end": _col(row, 4),
            "strand": _col(row, 5),
            "symbol": symbol,
            "status": _col(row, 7),
            "name": _col(row, 8),
            "marker_type": _col(row, 9),
            "feature_type": _col(row, 10),
            "synonyms": _split(_col(row, 11), seps="|"),
        }


# -- alleles (MGI_PhenotypicAllele.rpt) ----------------------------------------


def iter_alleles(path: Path) -> Iterator[dict[str, Any]]:
    """Yield allele records from MGI_PhenotypicAllele.rpt (``#``-comment header).

    Columns: allele id, symbol, name, allele type (generation method),
    attribute(s), PubMed id(s), marker id, marker symbol, RefSeq, Ensembl, ...,
    marker name.
    """
    for row in _read_tsv(path, skip_header=False):
        allele_id = _col(row, 0)
        if not allele_id or not allele_id.upper().startswith("MGI:"):
            continue
        yield {
            "allele_id": allele_id,
            "symbol": _col(row, 1),
            "name": _col(row, 2),
            "allele_type": _col(row, 3),
            "attributes": _split(_col(row, 4), seps="|"),
            "pubmed_ids": _split(_col(row, 5), seps="|,"),
            "marker_id": _col(row, 6),
            "marker_symbol": _col(row, 7),
        }


# -- gene -> phenotype (MGI_GenePheno.rpt) -------------------------------------


def iter_genepheno(path: Path) -> Iterator[dict[str, Any]]:
    """Yield gene->phenotype annotation rows from MGI_GenePheno.rpt (no header).

    Columns: allelic composition, allele symbol(s), allele id(s), genetic
    background, MP id, PubMed id, marker id, genotype id.
    """
    for row in _read_tsv(path, skip_header=False):
        marker_id = _col(row, 6)
        mp_id = _col(row, 4)
        if not marker_id or not mp_id or not mp_id.upper().startswith("MP:"):
            continue
        yield {
            "marker_id": marker_id,
            "mp_id": mp_id,
            "allelic_composition": _col(row, 0),
            "allele_symbols": _col(row, 1),
            "allele_ids": _split(_col(row, 2), seps="|,"),
            "genetic_background": _col(row, 3),
            "pubmed_id": _col(row, 5),
            "genotype_id": _col(row, 7),
        }


# -- MP vocabulary (VOC_MammalianPhenotype.rpt) --------------------------------


def iter_mp_terms(path: Path) -> Iterator[dict[str, Any]]:
    """Yield MP vocabulary rows (mp_id, name, definition); no header."""
    for row in _read_tsv(path, skip_header=False):
        mp_id = _col(row, 0)
        name = _col(row, 1)
        if not mp_id or not name or not mp_id.upper().startswith("MP:"):
            continue
        yield {"mp_id": mp_id, "name": name, "definition": _col(row, 2)}


# -- orthologs (HOM_MouseHumanSequence.rpt) ------------------------------------


def iter_orthologs(path: Path) -> Iterator[dict[str, Any]]:
    """Yield mouse->human ortholog records from HOM_MouseHumanSequence.rpt.

    Paired mouse + human rows share a ``DB Class Key``. For each mouse row we
    attach the human row(s) of the same class key. Also surfaces the mouse
    EntrezGene id for marker enrichment.

    Columns: DB Class Key, Organism, Taxon, Symbol, EntrezGene id, Mouse MGI id,
    HGNC id, OMIM Gene id, Genetic Location, Genome Coordinates, RefSeq nt,
    RefSeq protein, SwissProt.
    """
    mouse_rows: dict[str, list[list[str]]] = defaultdict(list)
    human_rows: dict[str, list[list[str]]] = defaultdict(list)
    for row in _read_tsv(path, skip_header=True):
        key = _col(row, 0)
        taxon = _col(row, 2)
        if not key:
            continue
        if taxon == MOUSE_TAXON_ID and _col(row, 5):
            mouse_rows[key].append(row)
        elif taxon == HUMAN_TAXON_ID:
            human_rows[key].append(row)

    for key, mice in mouse_rows.items():
        humans = human_rows.get(key, [])
        human = humans[0] if humans else None
        for m in mice:
            yield {
                "mgi_id": _col(m, 5),
                "mouse_symbol": _col(m, 3),
                "mouse_entrez_id": _col(m, 4),
                "human_symbol": _col(human, 3) if human else None,
                "human_entrez_id": _col(human, 4) if human else None,
                "hgnc_id": _col(human, 6) if human else None,
                "omim_gene_id": _col(human, 7) if human else None,
                "human_ensembl_id": None,
                "human_coords": _col(human, 9) if human else None,
            }


# -- disease models (MGI_DO.rpt) -----------------------------------------------


def iter_disease_models(path: Path) -> Iterator[dict[str, Any]]:
    """Yield mouse disease-model rows from MGI_DO.rpt (mouse rows only).

    Columns: DO id, DO name, OMIM ids, Organism, Taxon, Symbol, EntrezGene id,
    Mouse MGI id.
    """
    seen: set[tuple[str, str]] = set()
    for row in _read_tsv(path, skip_header=True):
        taxon = _col(row, 4)
        marker_id = _col(row, 7)
        doid = _col(row, 0)
        if taxon != MOUSE_TAXON_ID or not marker_id or not doid:
            continue
        dedupe = (marker_id, doid)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        yield {
            "marker_id": marker_id,
            "doid": doid,
            "disease_name": _col(row, 1),
            "omim_ids": _split(_col(row, 2), seps="|,"),
        }


# -- marker -> Ensembl (MRK_ENSEMBL.rpt) ---------------------------------------


def iter_marker_ensembl(path: Path) -> Iterator[tuple[str, str]]:
    """Yield ``(mgi_id, ensembl_gene_id)`` pairs from MRK_ENSEMBL.rpt (no header)."""
    for row in _read_tsv(path, skip_header=False):
        mgi_id = _col(row, 0)
        ensembl = _col(row, 5)
        if mgi_id and ensembl and ensembl.upper().startswith("ENSMUSG"):
            yield (mgi_id, ensembl)


# -- MP ontology graph (MPheno_OBO.ontology) -----------------------------------


def parse_mp_obo(text: str) -> dict[str, dict[str, Any]]:
    """Parse the MP OBO into ``{mp_id: {name, parents, obsolete}}``."""
    terms: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    in_term = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "[Term]":
            current = {"id": None, "name": None, "parents": [], "obsolete": False}
            in_term = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_term = False
            current = None
            continue
        if not in_term or current is None or ":" not in line:
            continue
        tag, _, value = line.partition(":")
        value = value.strip()
        if tag == "id" and value.upper().startswith("MP:"):
            current["id"] = value
            terms[value] = current
        elif tag == "name":
            current["name"] = value
        elif tag == "is_a":
            parent = value.split("!")[0].strip()
            if parent.upper().startswith("MP:"):
                current["parents"].append(parent)
        elif tag == "is_obsolete" and value.lower() == "true":
            current["obsolete"] = True
    return terms


def mp_closure_pairs(terms: dict[str, dict[str, Any]]) -> Iterator[tuple[str, str]]:
    """Yield ``(mp_id, ancestor_id)`` transitive-ancestor pairs incl. the self-pair."""
    cache: dict[str, set[str]] = {}

    def ancestors(mp_id: str, stack: frozenset[str]) -> set[str]:
        if mp_id in cache:
            return cache[mp_id]
        acc: set[str] = {mp_id}
        for parent in terms.get(mp_id, {}).get("parents", []):
            if parent in stack:  # cycle guard
                continue
            acc.add(parent)
            acc |= ancestors(parent, stack | {parent})
        cache[mp_id] = acc
        return acc

    for mp_id in terms:
        for anc in ancestors(mp_id, frozenset({mp_id})):
            yield (mp_id, anc)


def mp_top_systems(terms: dict[str, dict[str, Any]]) -> list[tuple[str, str, int]]:
    """Return the top-level MP systems (direct children of MP:0000001).

    These are the gene-page "Phenotype Overview" grid columns. Ordered
    alphabetically by display name for a stable layout.
    """
    systems = [
        (mp_id, term["name"])
        for mp_id, term in terms.items()
        if MP_ROOT in term.get("parents", []) and not term.get("obsolete") and term.get("name")
    ]
    systems.sort(key=lambda pair: pair[1].lower())
    return [(mp_id, name, order) for order, (mp_id, name) in enumerate(systems)]
