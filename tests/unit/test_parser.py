"""Unit tests for the MGI report parsers and the MP ontology graph."""

from __future__ import annotations

from pathlib import Path

from mgi_link.ingest import parser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_iter_markers_columns() -> None:
    markers = {m["mgi_id"]: m for m in parser.iter_markers(FIXTURES / "MRK_List2.rpt")}
    wt1 = markers["MGI:98968"]
    assert wt1["symbol"] == "Wt1"
    assert wt1["marker_type"] == "Gene"
    assert wt1["chromosome"] == "2"
    assert wt1["synonyms"] == ["Wt-1"]
    assert markers["MGI:97490"]["synonyms"] == ["Sey", "Gsfaey11"]


def test_iter_alleles_types() -> None:
    alleles = list(parser.iter_alleles(FIXTURES / "MGI_PhenotypicAllele.rpt"))
    wt1 = [a for a in alleles if a["marker_id"] == "MGI:98968"]
    types = sorted({a["allele_type"] for a in wt1})
    assert "Targeted" in types
    assert "Endonuclease-mediated" in types
    assert "Radiation induced" in types
    a0 = next(a for a in wt1 if a["allele_id"] == "MGI:1857268")
    assert a0["symbol"] == "Wt1<tm1Jae>"
    assert a0["attributes"] == ["Null/knockout"]


def test_iter_genepheno_columns() -> None:
    rows = list(parser.iter_genepheno(FIXTURES / "MGI_GenePheno.rpt"))
    wt1 = [r for r in rows if r["marker_id"] == "MGI:98968"]
    assert {r["mp_id"] for r in wt1} == {"MP:0002135", "MP:0003920", "MP:0001926", "MP:0008871"}
    r0 = next(r for r in wt1 if r["mp_id"] == "MP:0002135")
    assert r0["allele_ids"] == ["MGI:1857268"]
    assert r0["genetic_background"] == "involves: 129S2/SvPas"


def test_iter_orthologs_pairs_mouse_human() -> None:
    orthos = {
        o["mgi_id"]: o for o in parser.iter_orthologs(FIXTURES / "HOM_MouseHumanSequence.rpt")
    }
    wt1 = orthos["MGI:98968"]
    assert wt1["human_symbol"] == "WT1"
    assert wt1["hgnc_id"] == "HGNC:12796"
    assert wt1["omim_gene_id"] == "OMIM:607102"
    assert wt1["mouse_entrez_id"] == "22431"


def test_iter_disease_models_mouse_rows_only() -> None:
    diseases = list(parser.iter_disease_models(FIXTURES / "MGI_DO.rpt"))
    wt1 = [d for d in diseases if d["marker_id"] == "MGI:98968"]
    names = {d["disease_name"] for d in wt1}
    assert "Denys-Drash syndrome" in names
    assert all(d["marker_id"].startswith("MGI:") for d in diseases)


def test_mp_obo_graph_and_top_systems() -> None:
    terms = parser.parse_mp_obo((FIXTURES / "MPheno_OBO.ontology").read_text())
    assert terms["MP:0002135"]["parents"] == ["MP:0005367"]
    # nephroblastoma has two parents (neoplasm + renal/urinary)
    assert set(terms["MP:0008871"]["parents"]) == {"MP:0002006", "MP:0005367"}

    closure = set(parser.mp_closure_pairs(terms))
    assert ("MP:0002135", "MP:0002135") in closure  # self-pair
    assert ("MP:0002135", "MP:0005367") in closure  # direct ancestor
    assert ("MP:0002135", "MP:0000001") in closure  # transitive root
    assert ("MP:0008871", "MP:0005367") in closure  # via the second parent

    systems = parser.mp_top_systems(terms)
    names = [name for _id, name, _order in systems]
    assert "renal/urinary system phenotype" in names
    assert "mammalian phenotype" not in names  # the root itself is not a system
