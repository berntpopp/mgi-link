"""Unit tests for the MGI service orchestration against the fixture index."""

from __future__ import annotations

import pytest

from mgi_link.exceptions import InvalidInputError, NotFoundError
from mgi_link.services.mgi_service import MgiService


def test_resolve_by_symbol(service: MgiService) -> None:
    res = service.resolve("Wt1")
    assert res["mgi_id"] == "MGI:98968"
    assert res["match_type"] == "current"
    assert res["symbol"] == "Wt1"


def test_resolve_by_mgi_id(service: MgiService) -> None:
    assert service.resolve("MGI:98968")["match_type"] == "mgi_id"
    assert service.resolve("98968")["mgi_id"] == "MGI:98968"


def test_resolve_by_synonym(service: MgiService) -> None:
    res = service.resolve("Sey")  # Pax6 synonym
    assert res["mgi_id"] == "MGI:97490"
    assert res["match_type"] == "synonym"


def test_ambiguous_symbol_raises_with_candidates(service: MgiService) -> None:
    from mgi_link.exceptions import AmbiguousQueryError

    with pytest.raises(AmbiguousQueryError) as exc:
        service.resolve("Dup1")  # shared synonym across Fake1 + Fake2 in the fixture
    assert len(exc.value.candidates) >= 2


def test_resolve_by_human_ortholog(service: MgiService) -> None:
    # PAX6 (human) differs from Pax6 only in case -> resolves as a symbol match,
    # but HGNC id must go through the ortholog/xref path.
    res = service.resolve("HGNC:8620")
    assert res["mgi_id"] == "MGI:97490"
    assert res["match_type"] == "ortholog"


def test_resolve_not_found(service: MgiService) -> None:
    with pytest.raises(NotFoundError):
        service.resolve("Nonexistentxyz")


def test_resolve_empty(service: MgiService) -> None:
    with pytest.raises(InvalidInputError):
        service.resolve("   ")


def test_get_marker_includes_ortholog_and_summary(service: MgiService) -> None:
    marker = service.get_marker("Wt1")
    assert marker["mgi_id"] == "MGI:98968"
    assert marker["human_ortholog"]["symbol"] == "WT1"
    assert marker["human_ortholog"]["hgnc_id"] == "HGNC:12796"
    assert marker["summary"]["alleles_total"] == 5
    assert marker["summary"]["phenotypes"] == 4
    assert marker["summary"]["diseases"] == 2
    assert "GRCm39" in marker["location"]


def test_get_alleles_category_counts(service: MgiService) -> None:
    res = service.get_alleles("Wt1")
    assert res["total_alleles"] == 5
    assert res["category_counts"]["Targeted"] == 2
    assert res["category_counts"]["Endonuclease-mediated"] == 1
    assert res["category_counts"]["Radiation induced"] == 1
    assert res["category_counts"]["Chemically induced (other)"] == 1


def test_get_alleles_type_filter_alias(service: MgiService) -> None:
    res = service.get_alleles("Wt1", allele_type="knockout")  # alias -> Targeted
    assert res["allele_type_filter"] == "Targeted"
    assert all(a["allele_type"] == "Targeted" for a in res["alleles"])
    assert res["returned"] == 2


def test_get_phenotypes_and_summary(service: MgiService) -> None:
    res = service.get_phenotypes("Wt1")
    assert res["summary"]["phenotypes"] == 4
    assert res["summary"]["phenotyped_alleles"] == 2  # MGI:1857268 + MGI:2183640
    mp_ids = {a["mp_id"] for a in res["annotations"]}
    assert "MP:0002135" in mp_ids


def test_get_phenotypes_system_filter(service: MgiService) -> None:
    res = service.get_phenotypes("Wt1", mp_system="renal/urinary system")
    mp_ids = {a["mp_id"] for a in res["annotations"]}
    # abnormal kidney morphology + nephroblastoma both roll up to renal/urinary
    assert mp_ids == {"MP:0002135", "MP:0008871"}


def test_phenotype_overview_grid(service: MgiService) -> None:
    res = service.get_phenotype_overview("Wt1")
    systems = {s["system"]: s["count"] for s in res["systems"]}
    assert "renal/urinary system phenotype" in systems
    assert "cardiovascular system phenotype" in systems
    assert "reproductive system phenotype" in systems
    assert "tumorigenesis" in systems
    # nephroblastoma is annotated and rolls up to both renal/urinary and tumorigenesis
    renal = next(s for s in res["systems"] if s["system"] == "renal/urinary system phenotype")
    assert {t["mp_id"] for t in renal["terms"]} == {"MP:0002135", "MP:0008871"}


def test_get_diseases(service: MgiService) -> None:
    res = service.get_diseases("Wt1")
    assert res["count"] == 2
    names = {d["disease_name"] for d in res["diseases"]}
    assert "Denys-Drash syndrome" in names
    dd = next(d for d in res["diseases"] if d["disease_name"] == "Denys-Drash syndrome")
    assert dd["omim_ids"] == ["OMIM:194080"]


def test_get_ortholog_human_query(service: MgiService) -> None:
    res = service.get_ortholog("HGNC:12796")  # human WT1 -> mouse Wt1
    assert res["mgi_id"] == "MGI:98968"
    assert res["match_type"] == "ortholog"
    assert res["ortholog"]["human_symbol"]["value"] == "WT1"


def test_get_mp_term(service: MgiService) -> None:
    term = service.get_mp_term("MP:0008871")
    assert term["name"] == "nephroblastoma"
    parent_ids = {p["mp_id"] for p in term["parents"]}
    assert {"MP:0002006", "MP:0005367"} == parent_ids
    system_ids = {s["mp_id"] for s in term["top_level_systems"]}
    assert "MP:0005367" in system_ids


def test_search_phenotype_terms(service: MgiService) -> None:
    res = service.search_phenotype_terms("kidney")
    assert res["total"] >= 1
    assert res["returned"] == len(res["results"])
    assert any(h["mp_id"] == "MP:0002135" for h in res["results"])


def test_find_markers_by_phenotype_descendants(service: MgiService) -> None:
    # renal/urinary system -> includes Wt1 via abnormal kidney morphology + nephroblastoma
    res = service.find_markers_by_phenotype("MP:0005367", include_descendants=True)
    mgi_ids = {m["mgi_id"] for m in res["markers"]}
    assert "MGI:98968" in mgi_ids


def test_find_markers_by_phenotype_exact(service: MgiService) -> None:
    res = service.find_markers_by_phenotype("MP:0003920", include_descendants=False)
    mgi_ids = {m["mgi_id"] for m in res["markers"]}
    assert "MGI:98968" in mgi_ids  # Wt1 heart phenotype
    assert "MGI:97490" in mgi_ids  # Pax6 heart phenotype


def test_allele_count_labels_are_explicit(service: MgiService) -> None:
    marker = service.get_marker("Wt1")
    assert "alleles_total" in marker["summary"]
    assert "alleles" not in marker["summary"]
    pheno = service.get_phenotypes("Wt1")
    assert "phenotyped_alleles" in pheno["summary"]
    assert "alleles" not in pheno["summary"]


def test_alleles_truncation_contract(service: MgiService) -> None:
    out = service.get_alleles("Wt1", limit=1)
    assert out["total"] == out["total_alleles"]
    assert out["returned"] == 1
    assert out["truncated"] is True


def test_find_markers_exposes_total(service: MgiService) -> None:
    out = service.find_markers_by_phenotype("MP:0005367", limit=1)
    assert out["returned"] == 1
    assert out["total"] >= 1
    assert "truncated" in out


def test_search_terms_truncation(service: MgiService) -> None:
    out = service.search_phenotype_terms("abnormal", limit=1)
    assert out["returned"] == 1
    assert out["total"] >= out["returned"]


def test_phenotypes_term_view_dedup_and_order(service: MgiService) -> None:
    out = service.get_phenotypes("Wt1", mode="compact")
    assert out["view"] == "terms"
    ids = [a["mp_id"] for a in out["annotations"]]
    assert len(ids) == len(set(ids))  # deduplicated
    counts = [a["genotype_count"] for a in out["annotations"]]
    assert counts == sorted(counts, reverse=True)  # support-ordered
    assert out["total"] == out["summary"]["phenotypes"]
    assert "truncated" in out


def test_phenotypes_full_view_is_per_genotype(service: MgiService) -> None:
    out = service.get_phenotypes("Wt1", mode="full")
    assert out["view"] == "per_genotype"
    assert "genetic_background" in out["annotations"][0]


def test_phenotypes_minimal_has_no_duplicates(service: MgiService) -> None:
    out = service.get_phenotypes("Wt1", mode="minimal")
    pairs = [(a["mp_id"], a["mp_term"]) for a in out["annotations"]]
    assert len(pairs) == len(set(pairs))
    assert set(out["annotations"][0]) == {"mp_id", "mp_term", "genotype_count"}


def test_search_markers(service: MgiService) -> None:
    res = service.search("Wilms")
    assert any(r["mgi_id"] == "MGI:98968" for r in res["results"])


def test_search_exact_symbol_pinned_first(service: MgiService) -> None:
    out = service.search("Pax6", limit=25)
    assert out["results"][0]["symbol"] == "Pax6"
    assert out["results"][0]["match"] == "exact_symbol"
    assert out["total"] >= out["returned"]
    assert "truncated" in out


def test_search_exact_synonym_pinned_first(service: MgiService) -> None:
    # 'Sey' is a Pax6 synonym; exact synonym hits pin ahead of FTS noise.
    out = service.search("Sey", limit=25)
    assert out["results"][0]["mgi_id"] == "MGI:97490"
    assert out["results"][0]["match"] == "exact_synonym"


def test_diagnostics(service: MgiService) -> None:
    diag = service.get_diagnostics()
    assert diag["data_available"] is True
    assert diag["marker_count"] == 4
    assert diag["allele_count"] == 6
