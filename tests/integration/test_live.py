"""Opt-in integration tests against a real, fully-built MGI index.

Run with ``make test-integration`` (``pytest -m integration``). Skipped unless a
real ``data/mgi.sqlite`` exists (build it with ``make data`` /
``mgi-link-data build``). These assert the live pipeline reproduces the MGI gene
page for Wt1 (MGI:98968).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mgi_link.data.repository import MgiRepository
from mgi_link.services.mgi_service import MgiService

pytestmark = pytest.mark.integration

_DB = Path(__file__).resolve().parents[2] / "data" / "mgi.sqlite"


@pytest.fixture(scope="module")
def live_service() -> MgiService:
    if not _DB.exists():
        pytest.skip(f"No real MGI index at {_DB}; run `make data` first.")
    return MgiService(MgiRepository(_DB))


def test_wt1_resolves(live_service: MgiService) -> None:
    res = live_service.resolve("Wt1")
    assert res["mgi_id"] == "MGI:98968"
    assert res["symbol"] == "Wt1"


def test_wt1_human_ortholog(live_service: MgiService) -> None:
    orth = live_service.get_ortholog("Wt1")
    assert orth["ortholog"]["human_symbol"]["value"] == "WT1"
    assert orth["ortholog"]["hgnc_id"]["value"] == "HGNC:12796"


def test_wt1_alleles_have_targeted_and_endonuclease(live_service: MgiService) -> None:
    res = live_service.get_alleles("Wt1")
    assert res["total_alleles"] > 20
    assert res["category_counts"].get("Targeted", 0) >= 15
    assert res["category_counts"].get("Endonuclease-mediated", 0) >= 5


def test_wt1_phenotype_overview_includes_renal(live_service: MgiService) -> None:
    ov = live_service.get_phenotype_overview("Wt1")
    systems = {s["system"] for s in ov["systems"]}
    assert any("renal/urinary" in s for s in systems)
    assert any("reproductive" in s for s in systems)


def test_wt1_disease_models_include_denys_drash(live_service: MgiService) -> None:
    dz = live_service.get_diseases("Wt1")
    names = {d["disease_name"] for d in dz["diseases"]}
    assert any("Denys-Drash" in n for n in names)


def test_human_symbol_resolves_to_mouse(live_service: MgiService) -> None:
    # A human-only HGNC id resolves to the mouse ortholog.
    res = live_service.resolve("HGNC:12796")
    assert res["mgi_id"] == "MGI:98968"
    assert res["match_type"] == "ortholog"


def test_find_markers_by_kidney_phenotype(live_service: MgiService) -> None:
    # MP:0005367 renal/urinary system phenotype -> hundreds of genes. The
    # truncation contract exposes the true total even when the page is capped.
    res = live_service.find_markers_by_phenotype("MP:0005367", include_descendants=True, limit=500)
    assert res["total"] >= 50
    assert res["returned"] == len(res["markers"])
    assert res["truncated"] == (res["total"] > res["returned"])
    assert all(m["mgi_id"].startswith("MGI:") for m in res["markers"])
    # Descendants must broaden the set vs the exact-term-only query.
    exact = live_service.find_markers_by_phenotype(
        "MP:0005367", include_descendants=False, limit=500
    )
    assert res["total"] >= exact["total"]


def test_wt1_phenotypes_term_view_contract(live_service: MgiService) -> None:
    # The term view is deduplicated, support-ordered, and self-describing.
    res = live_service.get_phenotypes("Wt1")
    assert res["view"] == "terms"
    ids = [a["mp_id"] for a in res["annotations"]]
    assert len(ids) == len(set(ids))  # no duplicate terms
    counts = [a["genotype_count"] for a in res["annotations"]]
    assert counts == sorted(counts, reverse=True)
    assert res["total"] == res["summary"]["phenotypes"]
    assert res["truncated"] == (res["total"] > res["returned"])
