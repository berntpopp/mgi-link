"""The service serves resolve/get_marker from a fallback provider when cold."""

from __future__ import annotations

from typing import Any

import pytest

from mgi_link.exceptions import AmbiguousQueryError, DataUnavailableError
from mgi_link.services.mgi_service import MgiService

_WT1 = {
    "mgi_id": "MGI:98968",
    "symbol": "Wt1",
    "name": "WT1 transcription factor",
    "marker_type": "Gene",
    "feature_type": "protein coding gene",
    "chromosome": "2",
    "cm_position": None,
    "coord_start": 105_000_000,
    "coord_end": 105_050_000,
    "strand": "+",
    "status": None,
    "entrez_id": "22431",
    "ensembl_gene_id": None,
    "refseq_id": None,
    "synonyms": ["Wilms tumor 1 homolog"],
}


class _FakeProvider:
    """In-memory MarkerProvider; records calls so we can assert fail-fast."""

    def __init__(self) -> None:
        self.calls = 0

    def get_marker(self, mgi_id: str) -> dict[str, Any] | None:
        self.calls += 1
        return dict(_WT1) if mgi_id == "MGI:98968" else None

    def lookup_symbol(self, symbol: str) -> list[tuple[str, str]]:
        self.calls += 1
        s = symbol.upper()
        if s == "WT1":
            return [("MGI:98968", "current")]
        if s == "SHARED":  # ambiguous synonym
            return [("MGI:98968", "synonym"), ("MGI:99999", "synonym")]
        return []

    def lookup_by_xref(self, source: str, value: str) -> list[str]:
        self.calls += 1
        return ["MGI:98968"] if value.upper() == "WT1HUMAN" else []

    def get_ortholog(self, mgi_id: str) -> dict[str, Any] | None:
        self.calls += 1
        return {"human_symbol": "WT1", "hgnc_id": "HGNC:12796", "omim_gene_id": "607102"}


def test_resolve_uses_fallback_when_cold() -> None:
    svc = MgiService(None, fallback=_FakeProvider())
    out = svc.resolve("Wt1")
    assert out["mgi_id"] == "MGI:98968"
    assert out["source"] == "mousemine"


def test_get_marker_fallback_omits_summary_and_flags_partial() -> None:
    svc = MgiService(None, fallback=_FakeProvider())
    out = svc.get_marker("Wt1")
    assert out["mgi_id"] == "MGI:98968"
    assert out["source"] == "mousemine"
    assert out["partial"] is True
    assert "summary" not in out


def test_fallback_resolves_human_ortholog() -> None:
    svc = MgiService(None, fallback=_FakeProvider())
    out = svc.resolve("Wt1human")
    assert out["mgi_id"] == "MGI:98968"
    assert out["match_type"] == "ortholog"


def test_fallback_preserves_ambiguity_contract() -> None:
    svc = MgiService(None, fallback=_FakeProvider())
    with pytest.raises(AmbiguousQueryError) as exc:
        svc.resolve("shared")
    assert len(exc.value.candidates) == 2


def test_aggregate_tools_fail_fast_without_touching_fallback() -> None:
    fake = _FakeProvider()
    svc = MgiService(None, fallback=fake)
    with pytest.raises(DataUnavailableError):
        svc.get_phenotypes("Wt1")
    with pytest.raises(DataUnavailableError):
        svc.get_alleles("Wt1")
    assert fake.calls == 0  # repo path raised before any provider call


def test_repo_path_has_no_source_key(service: MgiService) -> None:
    # `service` fixture is the real repo-backed service (conftest).
    out = service.resolve("Wt1")
    assert "source" not in out
