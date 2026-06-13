# MouseMine Cold-Start Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the local SQLite index is unavailable AND `enable_live_fallback=True`, serve `resolve_marker` and `get_marker` from a live MouseMine (InterMine) query instead of returning `data_unavailable`; every other tool and the index-present path are unchanged.

**Architecture:** A narrow `MarkerProvider` Protocol (the four methods `resolve`/`get_marker` already call) is satisfied by both `MgiRepository` and a new `MouseMineClient`. `MgiService` gains an optional `fallback` provider and passes the provider explicitly to the resolution helper — identity tools use the fallback-aware provider, aggregate tools use the repo (fail-fast while cold). Live responses carry `source`/`partial` as plain-dict keys lifted into `_meta` by the tool layer.

**Tech Stack:** Python 3.12, FastMCP, httpx (sync, matches `ingest/downloader.py`), respx (HTTP mocking), pytest, mypy strict, ruff. Gate: `make ci-local`.

**Definition of done:** `make ci-local` green; with `enable_live_fallback=False` behavior is byte-identical to v0.2.0; with a fallback-backed service (no repo), `resolve_marker`/`get_marker` return index-shaped records carrying `_meta.source="mousemine"`, while every aggregate tool still returns `data_unavailable`.

**Conventions reminder:** TDD (failing test first). We are on branch `feature/mousemine-fallback`; commit after each task. 500-line/file budget enforced by `make lint-loc` (`mgi_link/api/mousemine.py` is new and focused; `mgi_service.py` is at 437 lines — watch the budget in Task 2).

**Source of truth:** `docs/superpowers/specs/2026-06-13-mgi-link-mousemine-fallback-design.md`.

---

## File structure

| File | Responsibility | Action |
|------|----------------|--------|
| `mgi_link/services/marker_provider.py` | `MarkerProvider` Protocol (4 methods) | Create (~20 lines) |
| `mgi_link/services/mgi_service.py` | `fallback` param, `_provider`/`using_fallback`, explicit-provider resolution, source/partial stamping, summary omission | Modify |
| `mgi_link/api/mousemine.py` | Sync InterMine client implementing `MarkerProvider`; query build, JSON parse, dedup, resilience, `close()` | Create (~180 lines) |
| `mgi_link/mcp/next_commands.py` | Source-aware `after_resolve`/`after_get_marker` | Modify |
| `mgi_link/mcp/tools/markers.py` | Lift `source`/`partial` into `_meta` for resolve/get_marker | Modify |
| `mgi_link/mcp/service_adapters.py` | Build `MouseMineClient` when enabled; close old client on reset/set | Modify |
| `mgi_link/mcp/tools/discovery.py` | `live_fallback` block in diagnostics | Modify |
| `mgi_link/mcp/capabilities.py` | `behavioral_defaults` cold-start note | Modify |
| `tests/unit/test_marker_provider.py` | Fake provider drives service fallback | Create |
| `tests/unit/test_mousemine.py` | respx-mocked client: mapping, dedup, errors, retry, close | Create |
| `tests/unit/test_service.py`, `test_tools_e2e.py`, `test_next_commands.py`, `test_config.py` | Extend | Modify |

---

### Task 1: `MarkerProvider` protocol + service fallback wiring (no network)

Delivers the entire service-side fallback behavior, tested with an in-memory fake provider — zero network, zero MouseMine code yet.

**Files:**
- Create: `mgi_link/services/marker_provider.py`
- Modify: `mgi_link/services/mgi_service.py`
- Test: `tests/unit/test_marker_provider.py` (new)

- [ ] **Step 1: Create the protocol** `mgi_link/services/marker_provider.py`

```python
"""Structural interface for marker resolution sources.

Both the offline ``MgiRepository`` and the live ``MouseMineClient`` satisfy this
Protocol, so ``MgiService.resolve``/``get_marker`` run unchanged against whichever
provider is live. Method names and parameter names mirror ``MgiRepository`` exactly
so the repository satisfies the Protocol structurally under mypy strict.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MarkerProvider(Protocol):
    """The four lookups the resolution cascade depends on."""

    def get_marker(self, mgi_id: str) -> dict[str, Any] | None: ...

    def lookup_symbol(self, symbol: str) -> list[tuple[str, str]]: ...

    def lookup_by_xref(self, source: str, value: str) -> list[str]: ...

    def get_ortholog(self, mgi_id: str) -> dict[str, Any] | None: ...
```

- [ ] **Step 2: Write the failing test** `tests/unit/test_marker_provider.py`

```python
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
```

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_marker_provider.py -v` — expect FAIL (`MgiService.__init__` takes no `fallback`).

- [ ] **Step 4: Add the fallback plumbing** to `mgi_link/services/mgi_service.py`.

Add the import near the other service imports:

```python
from mgi_link.services.marker_provider import MarkerProvider
```

Replace `__init__` and the `repo` property (current lines ~49-60) with:

```python
    def __init__(
        self, repository: MgiRepository | None, *, fallback: MarkerProvider | None = None
    ) -> None:
        """Wire the primary repository and an optional live fallback provider."""
        self._repo = repository
        self._fallback = fallback

    @property
    def repo(self) -> MgiRepository:
        """Return the repository or raise a data-unavailable error."""
        if self._repo is None:
            raise DataUnavailableError(
                "The local MGI index is not built yet. Run `mgi-link-data build`."
            )
        return self._repo

    @property
    def _provider(self) -> MarkerProvider:
        """The live marker source: the repo if built, else the fallback."""
        if self._repo is not None:
            return self._repo
        if self._fallback is not None:
            return self._fallback
        raise DataUnavailableError(
            "The local MGI index is not built yet. Run `mgi-link-data build`."
        )

    @property
    def using_fallback(self) -> bool:
        """True when the repo is absent and the fallback provider is serving."""
        return self._repo is None and self._fallback is not None

    def close(self) -> None:
        """Release the fallback client (the repo is closed by its owner)."""
        fallback = self._fallback
        if fallback is not None and hasattr(fallback, "close"):
            fallback.close()
```

- [ ] **Step 5: Thread the provider through resolution.** In `mgi_service.py`, change `_resolve_to_marker`, `_resolve_via_xref`, and `_ambiguity_error` to take an explicit `provider` and use it instead of `self.repo`.

Replace the `_resolve_to_marker` signature line and its `self.repo` uses:

```python
    def _resolve_to_marker(
        self, raw: str, provider: MarkerProvider
    ) -> tuple[dict[str, Any], str]:
        """Resolve any id/symbol/ortholog to ``(marker, match_type)`` or raise."""
        mgi_id = normalize_mgi_id(raw)
        if mgi_id:
            marker = provider.get_marker(mgi_id)
            if marker is not None:
                return marker, "mgi_id"
            raise NotFoundError(f"No MGI marker for {mgi_id}.")

        pairs = provider.lookup_symbol(raw)
        if pairs:
            best_type = pairs[0][1]
            best = [p for p in pairs if p[1] == best_type]
            if len(best) > 1:
                raise self._ambiguity_error(raw, best_type, best, provider)
            marker = provider.get_marker(best[0][0])
            if marker is not None:
                return marker, best_type

        ortholog_id = self._resolve_via_xref(raw, provider)
        if ortholog_id is not None:
            marker = provider.get_marker(ortholog_id)
            if marker is not None:
                return marker, "ortholog"

        raise NotFoundError(
            f"No MGI marker matches '{raw}'. Try an MGI id, a mouse symbol, or a "
            "human gene symbol/HGNC id for the ortholog."
        )

    def _resolve_via_xref(self, raw: str, provider: MarkerProvider) -> str | None:
        """Try the xref index (human symbol, HGNC, Ensembl) for a marker id."""
        candidates: list[str] = []
        source = infer_xref_source(raw)
        if source:
            candidates.append(source)
        if not looks_like_mgi_id(raw):
            candidates.append("human_symbol")
        for src in candidates:
            ids = provider.lookup_by_xref(src, raw)
            if ids:
                return ids[0]
        return None

    def _ambiguity_error(
        self, raw: str, best_type: str, best: list[tuple[str, str]], provider: MarkerProvider
    ) -> AmbiguousQueryError:
        candidates = [
            _brief(provider.get_marker(mid) or {"mgi_id": mid}, stype) for mid, stype in best
        ]
        return AmbiguousQueryError(
            f"'{raw}' is a {best_type} symbol for {len(best)} markers; pick one and call get_marker.",
            candidates=candidates,
        )
```

- [ ] **Step 6: Update the resolution callers.** In `resolve` (line ~146) and `get_marker` (line ~168) pass `self._provider`; in `get_alleles`, `get_phenotypes`, `get_phenotype_overview`, `get_diseases`, `get_ortholog` pass `self.repo`.

In `resolve`, change the call and stamp source:

```python
        marker, match_type = self._resolve_to_marker(raw, self._provider)
        record = {
            "query": raw,
            "mgi_id": marker.get("mgi_id"),
            "symbol": marker.get("symbol"),
            "name": marker.get("name"),
            "marker_type": marker.get("marker_type"),
            "feature_type": marker.get("feature_type"),
            "location": _location(marker),
            "match_type": match_type,
        }
        out = shape_resolution(record, mode)
        if self.using_fallback:
            out["source"] = "mousemine"
        return out
```

In `get_marker`, change the call, gate the ortholog/summary on the provider, and stamp:

```python
        marker, match_type = self._resolve_to_marker(raw, self._provider)
        mgi_id = marker["mgi_id"]
        record = dict(marker)
        record["requested_query"] = raw
        record["match_type"] = match_type
        record["location"] = _location(marker)
        ortholog = self._provider.get_ortholog(mgi_id)
        if ortholog:
            record["human_ortholog"] = {
                "symbol": ortholog.get("human_symbol"),
                "hgnc_id": ortholog.get("hgnc_id"),
                "omim_gene_id": ortholog.get("omim_gene_id"),
            }
        if not self.using_fallback:
            counts = self.repo.allele_category_counts(mgi_id)
            pheno = self.repo.phenotype_summary(mgi_id)
            record["summary"] = {
                "alleles_total": sum(counts.values()),
                "phenotypes": pheno["phenotypes"],
                "phenotype_references": pheno["references"],
                "diseases": len(self.repo.get_diseases(mgi_id)),
            }
        out = shape_marker(record, mode)
        if self.using_fallback:
            out["source"] = "mousemine"
            out["partial"] = True
        return out
```

For each of `get_alleles`, `get_phenotypes`, `get_phenotype_overview`, `get_diseases`, `get_ortholog`, change `self._resolve_to_marker((query or "").strip())` to `self._resolve_to_marker((query or "").strip(), self.repo)`.

> Note: `shape_marker`/`shape_resolution` may drop keys they don't recognise. `source`/`partial` are added to the shaped output AFTER shaping (above), so they survive. Confirm in Step 7.

- [ ] **Step 7: Run** `uv run pytest tests/unit/test_marker_provider.py tests/unit/test_service.py -v` — expect PASS. If `source` is missing on a fallback response, confirm it is set after the `shape_*` call, not before.

- [ ] **Step 8: Run** `uv run pytest tests/unit -q` then `make lint-loc` — expect PASS and `mgi_service.py` ≤ 500 lines. If over budget, extract `_resolve_to_marker`/`_resolve_via_xref`/`_ambiguity_error` into a `mgi_link/services/resolution.py` helper taking `provider` (free functions); leave a note and keep going.

- [ ] **Step 9: Commit**

```bash
git add mgi_link/services/marker_provider.py mgi_link/services/mgi_service.py tests/unit/test_marker_provider.py
git commit -m "feat: MgiService fallback provider for cold-start resolve/get_marker"
```

---

### Task 2: Source-aware next_commands + `_meta` lifting

**Files:**
- Modify: `mgi_link/mcp/next_commands.py`
- Modify: `mgi_link/mcp/tools/markers.py`
- Test: `tests/unit/test_next_commands.py`, `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Write the failing test** in `tests/unit/test_next_commands.py`

```python
def test_after_resolve_source_aware() -> None:
    from mgi_link.mcp.next_commands import after_resolve

    live = after_resolve({"mgi_id": "MGI:98968", "source": "mousemine"})
    tools = [c["tool"] for c in live]
    assert tools == ["get_marker", "get_mgi_diagnostics"]

    index = after_resolve({"mgi_id": "MGI:98968"})
    assert [c["tool"] for c in index] == ["get_marker", "get_marker_phenotypes"]


def test_after_get_marker_source_aware() -> None:
    from mgi_link.mcp.next_commands import after_get_marker

    live = after_get_marker({"mgi_id": "MGI:98968", "source": "mousemine"})
    assert [c["tool"] for c in live] == ["get_mgi_diagnostics", "get_server_capabilities"]

    index = after_get_marker({"mgi_id": "MGI:98968"})
    assert [c["tool"] for c in index] == ["get_marker_alleles", "get_phenotype_overview"]
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_next_commands.py -k source_aware -v` — expect FAIL.

- [ ] **Step 3: Make the chains source-aware** in `mgi_link/mcp/next_commands.py`. Replace `after_resolve` and `after_get_marker`:

```python
def after_resolve(resolution: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_marker: drill into the marker record + phenotypes.

    Live (MouseMine) results steer to get_marker + diagnostics, never the
    aggregate tools, which are data_unavailable while the index is cold.
    """
    mgi_id = resolution.get("mgi_id")
    if not mgi_id:
        return [cmd("search_markers", query=str(resolution.get("query", "")))]
    if resolution.get("source") == "mousemine":
        return [cmd("get_marker", query=mgi_id), cmd("get_mgi_diagnostics")]
    return [
        cmd("get_marker", query=mgi_id),
        cmd("get_marker_phenotypes", query=mgi_id),
    ]


def after_get_marker(marker: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker: offer alleles + the phenotype overview grid.

    Live (MouseMine) results steer to diagnostics/capabilities instead.
    """
    mgi_id = marker.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    if marker.get("source") == "mousemine":
        return [cmd("get_mgi_diagnostics"), cmd("get_server_capabilities")]
    return [
        cmd("get_marker_alleles", query=mgi_id),
        cmd("get_phenotype_overview", query=mgi_id),
    ]
```

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_next_commands.py -v` — expect PASS.

- [ ] **Step 5: Write the failing e2e test** in `tests/unit/test_tools_e2e.py`

```python
async def test_get_marker_live_source_in_meta_not_body(
    fallback_facade: Any, structured: Any
) -> None:
    payload = structured(await fallback_facade.call_tool("get_marker", {"query": "Wt1"}))
    assert payload["_meta"]["source"] == "mousemine"
    assert payload["_meta"]["partial"] is True
    assert "source" not in payload      # lifted out of the answer body
    assert "partial" not in payload
    tools = [c["tool"] for c in payload["_meta"]["next_commands"]]
    assert "get_marker_alleles" not in tools


async def test_resolve_index_has_no_source(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("resolve_marker", {"query": "Wt1"}))
    assert "source" not in payload["_meta"]
```

> The `fallback_facade` fixture (added in Step 6) is a FastMCP facade whose service is `MgiService(None, fallback=fake)` using the `_FakeProvider` from Task 1. The `facade`/`structured` fixtures already exist in `conftest.py`.

- [ ] **Step 6: Add the `fallback_facade` fixture** to `tests/conftest.py`. Mirror the existing `facade` fixture but inject a fallback-only service. Example (adapt to the existing fixture's construction):

```python
@pytest.fixture
def fallback_facade(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A FastMCP facade whose service has no repo, only a fake MouseMine fallback."""
    from tests.unit.test_marker_provider import _FakeProvider
    from mgi_link.mcp import service_adapters
    from mgi_link.services.mgi_service import MgiService

    service_adapters.set_mgi_service(MgiService(None, fallback=_FakeProvider()))
    from mgi_link.mcp.facade import build_facade  # match the existing import in `facade` fixture

    facade = build_facade()
    yield facade
    service_adapters.reset_mgi_service()
```

> Read the existing `facade` fixture first and copy its exact construction (the import path for building the FastMCP app may differ); only the injected service changes.

- [ ] **Step 7: Lift `source`/`partial` into `_meta`** in `mgi_link/mcp/tools/markers.py`. Replace the `resolve_marker` `call()`:

```python
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().resolve(query, response_mode)
            meta: dict[str, Any] = {"next_commands": after_resolve(payload)}
            source = payload.pop("source", None)
            if source:
                meta["source"] = source
            payload["_meta"] = meta
            return payload
```

Replace the `get_marker` `call()`:

```python
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_marker(query, response_mode)
            meta: dict[str, Any] = {"next_commands": after_get_marker(payload)}
            source = payload.pop("source", None)
            partial = payload.pop("partial", None)
            if source:
                meta["source"] = source
            if partial:
                meta["partial"] = partial
            payload["_meta"] = meta
            return payload
```

> `after_resolve(payload)`/`after_get_marker(payload)` are called BEFORE popping `source` so they see it. `run_mcp_tool` then merges this `_meta` with `tool`/`request_id`/`elapsed_ms`.

- [ ] **Step 8: Run** `uv run pytest tests/unit/test_tools_e2e.py tests/unit/test_next_commands.py -v` — expect PASS.

- [ ] **Step 9: Commit**

```bash
git add mgi_link/mcp/next_commands.py mgi_link/mcp/tools/markers.py tests/unit/test_next_commands.py tests/unit/test_tools_e2e.py tests/conftest.py
git commit -m "feat: source-aware next_commands and _meta.source/partial lifting"
```

---

### Task 3: `MouseMineClient` — query, parse, map, dedup (respx)

Implements the `MarkerProvider` against MouseMine. InterMine returns positional row lists, so parsing is deterministic and respx-mockable; the exact view PATHS are the one external unknown — Step 1 locks them against the live model.

**Files:**
- Create: `mgi_link/api/mousemine.py`
- Test: `tests/unit/test_mousemine.py` (new)

- [ ] **Step 1: Lock the InterMine view paths against the live model.** Run:

```bash
curl -s 'https://www.mousemine.org/mousemine/service/query/results?format=json&query=%3Cquery+model%3D%22genomic%22+view%3D%22Gene.primaryIdentifier+Gene.symbol+Gene.name+Gene.sequenceOntologyTerm.name+Gene.chromosome.primaryIdentifier+Gene.chromosomeLocation.start+Gene.chromosomeLocation.end+Gene.chromosomeLocation.strand+Gene.ncbiGeneNumber+Gene.synonyms.value%22%3E%3Cconstraint+path%3D%22Gene.primaryIdentifier%22+op%3D%22%3D%22+value%3D%22MGI%3A98968%22%2F%3E%3C%2Fquery%3E'
```

Expected: a JSON object `{"results": [[ "MGI:98968", "Wt1", "...", ...], ...]}` with repeated rows (one per synonym). If any path errors (`results` empty + an error message), open `https://www.mousemine.org/mousemine/service/model?format=json`, find the correct `Gene` field name, and adjust the `_GENE_VIEW` constant in Step 2 accordingly before continuing. The homologue paths (`Gene.homologues.homologue.*`) are verified the same way in the smoke test (Task 6).

- [ ] **Step 2: Write the failing test** `tests/unit/test_mousemine.py`

```python
"""respx-mocked unit tests for the live MouseMine InterMine client."""

from __future__ import annotations

import httpx
import pytest
import respx

from mgi_link.config import MouseMineConfig
from mgi_link.exceptions import RateLimitError, ServiceUnavailableError

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
                    ["MGI:98968", "Wt1", "WT1 tf", "protein coding gene", "2",
                     105000000, 105050000, "+", 22431, "Wilms tumor 1 homolog"],
                    ["MGI:98968", "Wt1", "WT1 tf", "protein coding gene", "2",
                     105000000, 105050000, "+", 22431, "Wt33"],
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
    respx.get(_RESULTS).mock(
        return_value=httpx.Response(
            200, json={"results": [["WT1", "HGNC:12796", "607102"]]}
        )
    )
    ortho = client.get_ortholog("MGI:98968")
    assert ortho == {"human_symbol": "WT1", "hgnc_id": "HGNC:12796", "omim_gene_id": "607102"}


@respx.mock
def test_lookup_by_xref_human_symbol(client) -> None:
    respx.get(_RESULTS).mock(
        return_value=httpx.Response(200, json={"results": [["MGI:98968"]]})
    )
    assert client.lookup_by_xref("human_symbol", "WT1") == ["MGI:98968"]
```

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_mousemine.py -v` — expect FAIL (module missing).

- [ ] **Step 4: Implement** `mgi_link/api/mousemine.py`

```python
"""Live MouseMine (InterMine) client — the cold-start marker fallback.

Implements the ``MarkerProvider`` Protocol against the MouseMine InterMine web
service. Used ONLY when the local SQLite index is unavailable AND
``enable_live_fallback`` is on. Synchronous (matches ``ingest/downloader.py``);
the rare blocking call during a cold start is an accepted trade-off.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import quoteattr

import httpx

from mgi_link.constants import HUMAN_TAXON_ID
from mgi_link.exceptions import RateLimitError, ServiceUnavailableError

if TYPE_CHECKING:
    from mgi_link.config import MouseMineConfig

_MOUSE_TAXON = "10090"
_BACKOFF_BASE = 0.5

# View column order for a Gene identity lookup (see Task 3 Step 1 verification).
_GENE_VIEW = (
    "Gene.primaryIdentifier",
    "Gene.symbol",
    "Gene.name",
    "Gene.sequenceOntologyTerm.name",
    "Gene.chromosome.primaryIdentifier",
    "Gene.chromosomeLocation.start",
    "Gene.chromosomeLocation.end",
    "Gene.chromosomeLocation.strand",
    "Gene.ncbiGeneNumber",
    "Gene.synonyms.value",
)
_SYMBOL_VIEW = ("Gene.primaryIdentifier", "Gene.symbol", "Gene.synonyms.value")
_ORTHOLOG_VIEW = (
    "Gene.homologues.homologue.symbol",
    "Gene.homologues.homologue.crossReferences.identifier",
    "Gene.homologues.homologue.organism.taxonId",
)


def _query(view: tuple[str, ...], path: str, op: str, value: str, *, extra: str | None = None) -> str:
    """Build a single-constraint InterMine PathQuery XML string."""
    extra_attr = f" extraValue={quoteattr(extra)}" if extra else ""
    return (
        f'<query model="genomic" view="{" ".join(view)}">'
        f"<constraint path={quoteattr(path)} op={quoteattr(op)} "
        f"value={quoteattr(value)}{extra_attr}/></query>"
    )


class MouseMineClient:
    """Sync InterMine client implementing the MarkerProvider Protocol."""

    def __init__(self, config: MouseMineConfig) -> None:
        """Open a pooled httpx client and prime the rate limiter."""
        self._config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout,
            headers={"User-Agent": config.user_agent},
            follow_redirects=True,
        )
        self._min_interval = 1.0 / config.rate_limit_per_s if config.rate_limit_per_s > 0 else 0.0
        self._last = 0.0

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    # -- HTTP ------------------------------------------------------------------

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _rows(self, query_xml: str) -> list[list[Any]]:
        """Issue the query with retries; return the positional results list."""
        params = {"query": query_xml, "format": "json"}
        last: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            self._throttle()
            try:
                resp = self._client.get("/query/results", params=params)
            except httpx.HTTPError as exc:  # network/timeout
                last = exc
                time.sleep(_BACKOFF_BASE * (2**attempt))
                continue
            if resp.status_code == 429:
                if attempt < self._config.max_retries:
                    time.sleep(_BACKOFF_BASE * (2**attempt))
                    continue
                raise RateLimitError()
            if resp.status_code >= 500:
                if attempt < self._config.max_retries:
                    time.sleep(_BACKOFF_BASE * (2**attempt))
                    continue
                raise ServiceUnavailableError()
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            return [list(r) for r in results]
        raise ServiceUnavailableError(str(last) if last else "MouseMine request failed.")

    # -- MarkerProvider --------------------------------------------------------

    def get_marker(self, mgi_id: str) -> dict[str, Any] | None:
        """Return a marker dict (repository.get_marker shape) or None."""
        rows = self._rows(_query(_GENE_VIEW, "Gene.primaryIdentifier", "=", mgi_id))
        return _marker_from_rows(rows)

    def lookup_symbol(self, symbol: str) -> list[tuple[str, str]]:
        """Resolve a symbol/synonym to (mgi_id, 'current'|'synonym') pairs."""
        rows = self._rows(
            _query(_SYMBOL_VIEW, "Gene", "LOOKUP", symbol, extra=_MOUSE_TAXON)
        )
        best: dict[str, str] = {}
        target = symbol.strip().upper()
        for r in rows:
            mgi_id, gene_symbol = r[0], r[1]
            stype = "current" if (gene_symbol or "").upper() == target else "synonym"
            if best.get(mgi_id) != "current":
                best[mgi_id] = stype
        pairs = [(mid, t) for mid, t in best.items()]
        pairs.sort(key=lambda p: 0 if p[1] == "current" else 1)
        return pairs

    def lookup_by_xref(self, source: str, value: str) -> list[str]:
        """Human symbol/HGNC -> mouse ortholog MGI ids (parity with the index)."""
        if source == "human_symbol":
            path = "Gene.homologues.homologue.symbol"
        elif source == "hgnc_id":
            path = "Gene.homologues.homologue.crossReferences.identifier"
        else:
            return []
        view = ("Gene.primaryIdentifier",)
        rows = self._rows(_query(view, path, "=", value))
        seen: list[str] = []
        for r in rows:
            if r[0] not in seen:
                seen.append(r[0])
        return seen

    def get_ortholog(self, mgi_id: str) -> dict[str, Any] | None:
        """Return the mouse->human ortholog dict (get_marker shape) or None."""
        rows = self._rows(_query(_ORTHOLOG_VIEW, "Gene.primaryIdentifier", "=", mgi_id))
        for r in rows:
            if len(r) >= 3 and str(r[2]) == HUMAN_TAXON_ID:
                ident = r[1] or ""
                return {
                    "human_symbol": r[0],
                    "hgnc_id": ident if str(ident).startswith("HGNC:") else None,
                    "omim_gene_id": None,
                }
        return None


def _marker_from_rows(rows: list[list[Any]]) -> dict[str, Any] | None:
    """Collapse repeated synonym-join rows into one marker (repo shape)."""
    if not rows:
        return None
    first = rows[0]
    synonyms: list[str] = []
    for r in rows:
        syn = r[9] if len(r) > 9 else None
        if syn and syn not in synonyms:
            synonyms.append(syn)
    entrez = first[8] if len(first) > 8 else None
    return {
        "mgi_id": first[0],
        "symbol": first[1],
        "name": first[2],
        "marker_type": "Gene",
        "feature_type": first[3],
        "chromosome": first[4],
        "cm_position": None,
        "coord_start": first[5],
        "coord_end": first[6],
        "strand": first[7],
        "status": None,
        "entrez_id": str(entrez) if entrez is not None else None,
        "ensembl_gene_id": None,
        "refseq_id": None,
        "synonyms": synonyms,
    }
```

> The `get_ortholog` test returns `["WT1", "HGNC:12796", "607102"]` but `_ORTHOLOG_VIEW` has 3 columns ending in `taxonId`. Align the test fixture's row to `_ORTHOLOG_VIEW` order during Step 1 verification: if you keep `omim_gene_id` out of the view, the test's third element must be the taxon id `"9606"` and the expected dict's `omim_gene_id` is `None`. Adjust the canned JSON in `test_get_ortholog_maps_human` to match the final view order so the assertion reflects real column positions.

- [ ] **Step 5: Run** `uv run pytest tests/unit/test_mousemine.py -v` — expect PASS. Fix column-index mismatches against the view constants until green.

- [ ] **Step 6: Commit**

```bash
git add mgi_link/api/mousemine.py tests/unit/test_mousemine.py
git commit -m "feat: MouseMineClient implementing MarkerProvider over InterMine"
```

---

### Task 4: Client resilience — retry, rate-limit, error mapping (respx)

**Files:**
- Modify: `mgi_link/api/mousemine.py` (only if Task 3 left gaps; likely none)
- Test: `tests/unit/test_mousemine.py`

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_mousemine.py`

```python
@respx.mock
def test_retries_on_500_then_succeeds(client) -> None:
    route = respx.get(_RESULTS).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"results": [["MGI:1", "A", "B", "g", "1", 1, 2, "+", 9, "s"]]}),
        ]
    )
    marker = client.get_marker("MGI:1")
    assert marker is not None
    assert route.call_count == 2


@respx.mock
def test_429_raises_rate_limit(client) -> None:
    respx.get(_RESULTS).mock(return_value=httpx.Response(429))
    with pytest.raises(RateLimitError):
        client.get_marker("MGI:1")


@respx.mock
def test_persistent_500_raises_service_unavailable(client) -> None:
    respx.get(_RESULTS).mock(return_value=httpx.Response(503))
    with pytest.raises(ServiceUnavailableError):
        client.get_marker("MGI:1")


@respx.mock
def test_network_error_raises_service_unavailable(client) -> None:
    respx.get(_RESULTS).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ServiceUnavailableError):
        client.get_marker("MGI:1")


def test_close_closes_client(client) -> None:
    client.close()
    assert client._client.is_closed
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_mousemine.py -k "retr or rate or service or network or close" -v` — expect PASS (Task 3's `_rows` already implements this). If a test fails, fix `_rows` retry/raise logic to satisfy it.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_mousemine.py mgi_link/api/mousemine.py
git commit -m "test: MouseMineClient retry, rate-limit, and error mapping"
```

---

### Task 5: Wiring — adapters, diagnostics, capabilities, config

**Files:**
- Modify: `mgi_link/mcp/service_adapters.py`
- Modify: `mgi_link/mcp/tools/discovery.py`
- Modify: `mgi_link/mcp/capabilities.py`
- Test: `tests/unit/test_config.py`, `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Write the failing test** in `tests/unit/test_tools_e2e.py`

```python
async def test_diagnostics_reports_live_fallback(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_mgi_diagnostics", {}))
    assert "live_fallback" in payload
    assert "enabled" in payload["live_fallback"]
    assert "base_url" in payload["live_fallback"]
```

And in `tests/unit/test_config.py` (create if absent):

```python
def test_mousemine_defaults_off() -> None:
    from mgi_link.config import MouseMineConfig

    cfg = MouseMineConfig()
    assert cfg.enable_live_fallback is False
    assert cfg.user_agent.startswith("mgi-link/")
```

- [ ] **Step 2: Run** both — expect FAIL (`live_fallback` missing).

- [ ] **Step 3: Build the client when enabled** in `mgi_link/mcp/service_adapters.py`. Replace `_build_service` and add close-on-swap to `reset`/`set`:

```python
from mgi_link.api.mousemine import MouseMineClient


def _build_service() -> MgiService:
    repo: MgiRepository | None = None
    db_path = settings.data.db_path
    if db_path.exists():
        try:
            repo = MgiRepository(db_path)
        except DataUnavailableError as exc:  # pragma: no cover - corrupt db
            logger.warning("mgi_repo_open_failed path=%s err=%s", db_path, exc)
    fallback: MouseMineClient | None = None
    if settings.mousemine.enable_live_fallback:
        fallback = MouseMineClient(settings.mousemine)
        logger.info("mgi_live_fallback_enabled base_url=%s", settings.mousemine.base_url)
    return MgiService(repo, fallback=fallback)


def get_mgi_service() -> MgiService:
    """Return a process-wide :class:`MgiService` (built on first use)."""
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def reset_mgi_service() -> None:
    """Drop the cached service (closing its fallback client) so the next call re-opens."""
    global _service
    if _service is not None:
        _service.close()
    _service = None


def set_mgi_service(service: MgiService | None) -> None:
    """Override the singleton (used by tests); closes any previous service."""
    global _service
    if _service is not None and _service is not service:
        _service.close()
    _service = service
```

- [ ] **Step 4: Add the diagnostics block.** In `mgi_link/mcp/tools/discovery.py` `get_mgi_diagnostics`'s `call()`, after `payload["build"] = build_info()` add:

```python
            payload["live_fallback"] = {
                "enabled": settings.mousemine.enable_live_fallback,
                "base_url": settings.mousemine.base_url,
            }
```

Ensure `from mgi_link.config import settings` is imported in `discovery.py` (add if missing). Add `live_fallback=_OBJ` to `DIAGNOSTICS_SCHEMA` in `schemas.py`.

- [ ] **Step 5: Document in capabilities.** In `mgi_link/mcp/capabilities.py` `behavioral_defaults`, add:

```python
            "cold_start_fallback": (
                "When the local index is unavailable AND mousemine.enable_live_fallback "
                "is on, resolve_marker and get_marker serve from a live MouseMine query "
                "(genes only; _meta.source='mousemine'; get_marker omits summary counts "
                "and sets _meta.partial). All other tools return data_unavailable while "
                "the index is cold. Default off: behavior is unchanged."
            ),
```

- [ ] **Step 6: Run** `uv run pytest tests/unit/test_tools_e2e.py tests/unit/test_config.py -v` — expect PASS.

- [ ] **Step 7: Commit**

```bash
git add mgi_link/mcp/service_adapters.py mgi_link/mcp/tools/discovery.py mgi_link/mcp/capabilities.py mgi_link/mcp/schemas.py tests/unit/test_tools_e2e.py tests/unit/test_config.py
git commit -m "feat: wire MouseMine fallback into adapters, diagnostics, capabilities"
```

---

### Task 6: Full verification + optional live smoke test

**Files:**
- Create: `tests/integration/test_mousemine_live.py` (opt-in)
- Verify: whole suite + `make ci-local`

- [ ] **Step 1: Add an opt-in live smoke test** `tests/integration/test_mousemine_live.py` (mirrors the existing `tests/integration` opt-in pattern; not run in `ci-local`):

```python
"""Opt-in live MouseMine smoke test. Run with: uv run pytest -m integration."""

from __future__ import annotations

import pytest

from mgi_link.config import MouseMineConfig

pytestmark = pytest.mark.integration


def test_live_get_marker_wt1() -> None:
    from mgi_link.api.mousemine import MouseMineClient

    client = MouseMineClient(MouseMineConfig())
    try:
        marker = client.get_marker("MGI:98968")
    finally:
        client.close()
    assert marker is not None
    assert marker["symbol"] == "Wt1"
    assert marker["chromosome"]


def test_live_resolve_human_ortholog() -> None:
    from mgi_link.api.mousemine import MouseMineClient

    client = MouseMineClient(MouseMineConfig())
    try:
        ids = client.lookup_by_xref("human_symbol", "WT1")
    finally:
        client.close()
    assert "MGI:98968" in ids
```

> Confirm `integration` is a registered marker in `pyproject.toml`/`pytest.ini`; the existing `tests/integration/test_live.py` already establishes the pattern — copy its marker usage.

- [ ] **Step 2: Run the full unit suite** `uv run pytest tests/unit -q` — expect all PASS.

- [ ] **Step 3: Run** `make ci-local` — must be green (format-check, lint-ci, lint-loc, typecheck, test-fast). If `mgi_service.py` exceeds 500 lines, perform the `resolution.py` extraction noted in Task 1 Step 8.

- [ ] **Step 4: Optional live smoke** (requires network) `uv run pytest tests/integration/test_mousemine_live.py -m integration -v`. If MouseMine field paths differ from `_GENE_VIEW`/`_ORTHOLOG_VIEW`, adjust the constants in `mousemine.py` and re-run Task 3 unit tests + this smoke test until both pass.

- [ ] **Step 5: Final `make ci-local`** — green. Done.

---

## Self-Review

**Spec coverage:**
- §2 scope (cold + enabled, identity tools only, gene-only) → Task 1 (`using_fallback`, `self.repo` for aggregate tools), Task 5 (build only when enabled), Task 3 (`Gene` views).
- §3 MarkerProvider + explicit provider → Task 1 (protocol, `_resolve_to_marker(raw, provider)`).
- §4 client (queries, refseq_id, Gene class, dedup, resilience, error mapping) → Tasks 3, 4.
- §5 byte-identical default + source/partial via plain dict lifted to `_meta` → Task 1 (stamp after shaping), Task 2 (lift), `test_repo_path_has_no_source_key` / `test_resolve_index_has_no_source`.
- §6 wiring (init, provider gating, source-aware next_commands, lifecycle, diagnostics, capabilities) → Tasks 1, 2, 5.
- §7 testing (mousemine unit, service fake, e2e, config) → Tasks 1–5; smoke → Task 6.
- §8 out of scope (non-gene SequenceFeature) → respected (Gene-only; deferred).

**Placeholder scan:** No "TBD"/"add error handling"-style gaps. The one external unknown (exact InterMine view paths) is locked by a concrete verification step (Task 3 Step 1) with my best-effort defaults and an opt-in live smoke (Task 6) — code is complete, not deferred.

**Type consistency:** `MarkerProvider` method/param names (`get_marker(mgi_id)`, `lookup_symbol(symbol)`, `lookup_by_xref(source, value)`, `get_ortholog(mgi_id)`) match `MgiRepository` exactly (verified against `repository.py`), so the repo satisfies the Protocol under mypy strict. `MgiService(None, fallback=...)` keyword used identically in Tasks 1, 2, 5. `using_fallback`/`_provider`/`close()` referenced consistently. Marker dict keys match `MARKER_SCALAR_FIELDS` and exclude `symbol_upper` (matching `repository._marker_from_row`). `source`/`partial` are body keys in the service (Task 1) and `_meta` keys after the tool lift (Task 2) — the e2e test asserts both the presence in `_meta` and the absence from the body.
