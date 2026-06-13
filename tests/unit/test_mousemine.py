"""respx-mocked unit tests for the live MouseMine InterMine client."""

from __future__ import annotations

import httpx
import pytest
import respx

from mgi_link.config import MouseMineConfig
from mgi_link.exceptions import (  # noqa: F401 - used in Task 4 retry tests
    RateLimitError,
    ServiceUnavailableError,
)

_BASE = "https://www.mousemine.org/mousemine/service"
_RESULTS = f"{_BASE}/query/results"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    # Neutralise sleeps so retry/throttle tests are instant.
    monkeypatch.setattr("mgi_link.api.mousemine.time.sleep", lambda _s: None)
    from mgi_link.api.mousemine import MouseMineClient

    cfg = MouseMineConfig(base_url=_BASE, rate_limit_per_s=10.0, max_retries=2)
    c = MouseMineClient(cfg)
    yield c
    c.close()


@respx.mock
def test_get_marker_maps_and_dedupes_synonyms(client) -> None:
    # Two rows for the same gene (synonym join) must collapse to one marker.
    respx.get(_RESULTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    [
                        "MGI:98968",
                        "Wt1",
                        "WT1 tf",
                        "protein coding gene",
                        "2",
                        105000000,
                        105050000,
                        "+",
                        22431,
                        "Wilms tumor 1 homolog",
                    ],
                    [
                        "MGI:98968",
                        "Wt1",
                        "WT1 tf",
                        "protein coding gene",
                        "2",
                        105000000,
                        105050000,
                        "+",
                        22431,
                        "Wt33",
                    ],
                ]
            },
        )
    )
    marker = client.get_marker("MGI:98968")
    assert marker is not None
    assert marker["mgi_id"] == "MGI:98968"
    assert marker["symbol"] == "Wt1"
    assert marker["marker_type"] == "Gene"
    assert marker["entrez_id"] == "22431"
    assert sorted(marker["synonyms"]) == ["Wilms tumor 1 homolog", "Wt33"]
    assert "symbol_upper" not in marker  # matches repository.get_marker output


@respx.mock
def test_get_marker_empty_is_none(client) -> None:
    respx.get(_RESULTS).mock(return_value=httpx.Response(200, json={"results": []}))
    assert client.get_marker("MGI:00000") is None


@respx.mock
def test_lookup_symbol_classifies_current_vs_synonym(client) -> None:
    respx.get(_RESULTS).mock(
        return_value=httpx.Response(
            200,
            json={"results": [["MGI:98968", "Wt1", "Wt1"], ["MGI:98968", "Wt1", "Wt33"]]},
        )
    )
    pairs = client.lookup_symbol("Wt1")
    assert pairs == [("MGI:98968", "current")]  # deduped, current wins


@respx.mock
def test_get_ortholog_maps_human(client) -> None:
    # Row order matches _ORTHOLOG_VIEW: (homologue.symbol, homologue HGNC xref id, homologue taxonId)
    respx.get(_RESULTS).mock(
        return_value=httpx.Response(200, json={"results": [["WT1", "HGNC:12796", "9606"]]})
    )
    ortho = client.get_ortholog("MGI:98968")
    assert ortho == {"human_symbol": "WT1", "hgnc_id": "HGNC:12796", "omim_gene_id": None}


@respx.mock
def test_lookup_by_xref_human_symbol(client) -> None:
    respx.get(_RESULTS).mock(return_value=httpx.Response(200, json={"results": [["MGI:98968"]]}))
    assert client.lookup_by_xref("human_symbol", "WT1") == ["MGI:98968"]
