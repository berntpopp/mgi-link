# mgi-link Evaluation Remediation — Implementation Plan

> Historical record

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all ten findings (F1–F10) from `MCP_EVALUATION.md` to lift the live grade from B+ (7.5/10) to >9.5/10, prioritising grounding safety (silent truncation).

**Architecture:** Add a uniform truncation contract (`total/returned/limit/truncated`) to every list tool; redesign `get_marker_phenotypes` into a deduplicated, support-ordered term view (default) with an opt-in per-genotype `full` view; boost exact matches in `search_markers`; disambiguate allele-count labels; add `_meta.elapsed_ms`; prove the ambiguity contract with a fixture. Services stay plain-dict; the MCP envelope layer is untouched except for timing.

**Tech Stack:** Python 3.12, FastMCP, SQLite/FTS5, pydantic, pytest (real fixture index), mypy strict, ruff. Gate: `make ci-local`.

**Definition of done:** `make ci-local` green AND a live re-probe of `data/mgi.sqlite` confirms Pkd1 default lists `polycystic kidney` + truncation contract, `search_markers("Pax6")` returns the gene at rank 1, `find_markers_by_phenotype` exposes a real `total`.

**Conventions reminder:** TDD (failing test first); commits are skipped (repo is not git-initialised) — instead run the named test after each task and `make ci-local` at the end of each task group. 500-line/file budget enforced by `make lint-loc`.

---

### Task 1: Truncation foundation — `page_fields` + `widen_cmd` + repository counts

**Files:**
- Create: `mgi_link/services/pagination.py`
- Modify: `mgi_link/mcp/next_commands.py` (add `widen_cmd`)
- Modify: `mgi_link/data/repository.py` (add count + term methods)
- Test: `tests/unit/test_pagination.py` (new), `tests/unit/test_service.py`

- [ ] **Step 1: Write failing test** `tests/unit/test_pagination.py`

```python
"""Unit tests for the truncation-contract helper."""

from __future__ import annotations

from mgi_link.services.pagination import page_fields


def test_page_fields_truncated() -> None:
    assert page_fields(total=126, returned=100, limit=100) == {
        "total": 126,
        "returned": 100,
        "limit": 100,
        "truncated": True,
    }


def test_page_fields_complete() -> None:
    out = page_fields(total=5, returned=5, limit=200)
    assert out["truncated"] is False
    assert out["total"] == 5
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_pagination.py -v` — expect FAIL (module missing).

- [ ] **Step 3: Implement** `mgi_link/services/pagination.py`

```python
"""Uniform truncation contract for list-returning tools.

Every list tool returns ``total`` (matches before the cap), ``returned`` (rows in
this payload), ``limit`` (cap applied), and ``truncated`` (``total > returned``) so
an LLM can never mistake a capped list for a complete one.
"""

from __future__ import annotations


def page_fields(*, total: int, returned: int, limit: int) -> dict[str, int | bool]:
    """Return the canonical truncation block."""
    return {
        "total": total,
        "returned": returned,
        "limit": limit,
        "truncated": total > returned,
    }
```

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_pagination.py -v` — expect PASS.

- [ ] **Step 5: Add `widen_cmd`** to `mgi_link/mcp/next_commands.py` (after `cmd`, near line 13)

```python
def widen_cmd(
    tool: str, base_args: dict[str, Any], total: int, ceiling: int
) -> dict[str, Any]:
    """A ready-to-call step that re-runs ``tool`` with ``limit`` raised to fit."""
    return cmd(tool, **{**base_args, "limit": min(total, ceiling)})
```

- [ ] **Step 6: Add repository count + term methods** to `mgi_link/data/repository.py`.

In the `# -- search` section, add `count_search` after `search`:

```python
    def count_search(self, query: str, *, marker_type: str | None = None) -> int:
        """Total markers matching the FTS query (before any limit)."""
        match = self._fts_query(query)
        sql = (
            "SELECT COUNT(*) AS n FROM marker_fts "
            "JOIN marker m ON m.mgi_id = marker_fts.mgi_id WHERE marker_fts MATCH ?"
        )
        params: list[Any] = [match]
        if marker_type:
            sql += " AND m.marker_type = ?"
            params.append(marker_type)
        try:
            return int(self._conn.execute(sql, tuple(params)).fetchone()["n"])
        except sqlite3.Error:
            pattern = "%" + query.upper().replace("%", "").replace("_", "") + "%"
            like = "SELECT COUNT(*) AS n FROM marker WHERE (symbol_upper LIKE ? OR UPPER(name) LIKE ?)"
            lparams: list[Any] = [pattern, pattern]
            if marker_type:
                like += " AND marker_type = ?"
                lparams.append(marker_type)
            return int(self._conn.execute(like, tuple(lparams)).fetchone()["n"])
```

In the `# -- phenotypes` section, add term aggregation + counts after `get_phenotypes`:

```python
    def phenotype_terms(
        self, marker_id: str, *, system_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Distinct MP terms for a marker with genotype support, support-ordered."""
        sql = (
            "SELECT gp.mp_id, t.name AS mp_term, "
            "COUNT(DISTINCT gp.genotype_id) AS genotype_count, "
            "(SELECT group_concat(DISTINCT s.name) FROM mp_top_system s "
            " JOIN mp_closure c ON c.ancestor_id = s.mp_id WHERE c.mp_id = gp.mp_id) AS systems "
            "FROM genopheno gp LEFT JOIN mp_term t ON t.mp_id = gp.mp_id "
            "WHERE gp.marker_id = ?"
        )
        params: list[Any] = [marker_id]
        if system_id:
            sql += " AND gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            params.append(system_id)
        sql += " GROUP BY gp.mp_id, t.name ORDER BY genotype_count DESC, t.name"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "mp_id": r["mp_id"],
                "mp_term": r["mp_term"],
                "genotype_count": r["genotype_count"],
                "systems": r["systems"].split(",") if r["systems"] else [],
            }
            for r in rows
        ]

    def count_phenotype_terms(self, marker_id: str, *, system_id: str | None = None) -> int:
        """Distinct MP-term count for a marker (term-view total)."""
        sql = "SELECT COUNT(DISTINCT gp.mp_id) AS n FROM genopheno gp WHERE gp.marker_id = ?"
        params: list[Any] = [marker_id]
        if system_id:
            sql += " AND gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            params.append(system_id)
        return int(self._conn.execute(sql, tuple(params)).fetchone()["n"])

    def count_phenotype_rows(self, marker_id: str, *, system_id: str | None = None) -> int:
        """Per-genotype annotation-row count for a marker (full-view total)."""
        sql = "SELECT COUNT(*) AS n FROM genopheno gp WHERE gp.marker_id = ?"
        params: list[Any] = [marker_id]
        if system_id:
            sql += " AND gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            params.append(system_id)
        return int(self._conn.execute(sql, tuple(params)).fetchone()["n"])
```

In the reverse-lookup area, add `count_markers_by_phenotype` after `markers_by_phenotype`:

```python
    def count_markers_by_phenotype(self, mp_id: str, *, include_descendants: bool) -> int:
        """Total distinct markers annotated with an MP term (reverse-lookup total)."""
        if include_descendants:
            sql = (
                "SELECT COUNT(DISTINCT gp.marker_id) AS n FROM genopheno gp "
                "WHERE gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            )
        else:
            sql = "SELECT COUNT(DISTINCT gp.marker_id) AS n FROM genopheno gp WHERE gp.mp_id = ?"
        return int(self._conn.execute(sql, (mp_id,)).fetchone()["n"])
```

In the `# -- ontology` section, add `count_mp` after `search_mp`:

```python
    def count_mp(self, query: str) -> int:
        """Total MP terms matching the FTS query (before any limit)."""
        match = self._fts_query(query)
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM mp_fts WHERE mp_fts MATCH ?", (match,)
            ).fetchone()
            return int(row["n"])
        except sqlite3.Error:
            pattern = "%" + query.upper().replace("%", "").replace("_", "") + "%"
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM mp_term WHERE UPPER(name) LIKE ?", (pattern,)
            ).fetchone()
            return int(row["n"])
```

- [ ] **Step 7: Run** `uv run pytest tests/unit/test_pagination.py tests/unit/test_service.py -v` — expect PASS. Run `make lint-loc` to confirm `repository.py` is still ≤500 lines; if not, extract the ontology methods (`get_mp_term`, `search_mp`, `count_mp`, `top_systems`) into a follow-up split (note for Task 9 self-review).

---

### Task 2: `search_markers` exact-match boost + truncation (F3, F1-search)

**Files:**
- Modify: `mgi_link/data/repository.py` (`search` rewrite, add `match` field)
- Modify: `mgi_link/services/mgi_service.py` (`search` wiring)
- Modify: `mgi_link/services/shaping.py` (`shape_summary` keeps `match`)
- Modify: `mgi_link/mcp/next_commands.py` (`after_search` widen-aware)
- Modify: `mgi_link/mcp/tools/markers.py` (call + description)
- Modify: `mgi_link/mcp/schemas.py` (SEARCH_SCHEMA)
- Test: `tests/unit/test_service.py`, `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Write failing test** in `tests/unit/test_service.py`

```python
def test_search_exact_symbol_pinned_first(service: MgiService) -> None:
    # Pax6 is an exact gene symbol; FTS alone buries it under Sey/decoys.
    out = service.search("Pax6", limit=25)
    assert out["results"][0]["symbol"] == "Pax6"
    assert out["results"][0]["match"] == "exact_symbol"
    assert out["total"] >= out["returned"]
    assert "truncated" in out
```

> Note: the fixture index must contain `Pax6` (MGI:97490) plus ≥1 decoy whose symbol/name contains "Pax6" (e.g. the `Sey` synonym row). If the fixtures lack a decoy that out-ranks Pax6, the test still passes (Pax6 first); add a decoy marker to `tests/fixtures/MRK_List2.rpt` only if needed to make the ordering meaningful.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_service.py::test_search_exact_symbol_pinned_first -v` — expect FAIL (`match` missing / order wrong).

- [ ] **Step 3: Rewrite `repository.search`** in `mgi_link/data/repository.py` to merge exact-first then FTS:

```python
    def search(
        self, query: str, *, limit: int, marker_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Exact symbol/synonym hits pinned first, then FTS relevance."""
        q_upper = query.strip().upper()
        exact_sql = (
            "SELECT m.mgi_id, m.symbol, m.name, m.marker_type, m.feature_type, "
            "m.chromosome, ml.symbol_type FROM marker_lookup ml "
            "JOIN marker m ON m.mgi_id = ml.mgi_id WHERE ml.lookup_symbol = ?"
        )
        eparams: list[Any] = [q_upper]
        if marker_type:
            exact_sql += " AND m.marker_type = ?"
            eparams.append(marker_type)
        exact_sql += " ORDER BY CASE ml.symbol_type WHEN 'current' THEN 0 ELSE 1 END"
        exact_rows = self._conn.execute(exact_sql, tuple(eparams)).fetchall()

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for r in exact_rows:
            if r["mgi_id"] in seen:
                continue
            seen.add(r["mgi_id"])
            summary = self._summary_from_row(r)
            summary["match"] = (
                "exact_symbol" if r["symbol_type"] == "current" else "exact_synonym"
            )
            results.append(summary)

        if len(results) < limit:
            for r in self._fts_rows(query, limit=limit + len(results), marker_type=marker_type):
                if r["mgi_id"] in seen:
                    continue
                seen.add(r["mgi_id"])
                summary = self._summary_from_row(r)
                summary["match"] = "fts"
                results.append(summary)
                if len(results) >= limit:
                    break
        return results[:limit]

    def _fts_rows(
        self, query: str, *, limit: int, marker_type: str | None
    ) -> list[sqlite3.Row]:
        """Raw FTS rows (with LIKE fallback) — used by search()."""
        match = self._fts_query(query)
        sql = (
            "SELECT m.mgi_id, m.symbol, m.name, m.marker_type, m.feature_type, "
            "m.chromosome, bm25(marker_fts) AS rank "
            "FROM marker_fts JOIN marker m ON m.mgi_id = marker_fts.mgi_id "
            "WHERE marker_fts MATCH ?"
        )
        params: list[Any] = [match]
        if marker_type:
            sql += " AND m.marker_type = ?"
            params.append(marker_type)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            return self._conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error:
            return self._search_like(query, limit=limit, marker_type=marker_type)
```

> The old `search` body (the FTS query) is now `_fts_rows`; delete the old inline FTS code from `search`. `_summary_from_row` and `_search_like` are unchanged.

- [ ] **Step 4: Wire `total` + `match` passthrough** in `mgi_link/services/mgi_service.py` `search` (replace the return block, ~lines 196-202):

```python
        hits = self.repo.search(raw, limit=limit, marker_type=marker_type)
        total = self.repo.count_search(raw, marker_type=marker_type)
        results = [shape_summary(h, mode) for h in hits]
        return {
            "query": raw,
            "marker_type": marker_type,
            **page_fields(total=total, returned=len(results), limit=limit),
            "results": results,
        }
```

Add the import near the other service imports: `from mgi_link.services.pagination import page_fields`.

- [ ] **Step 5: Keep `match` through shaping.** In `mgi_link/services/shaping.py` `shape_summary`, add `"match"` to the minimal keep-set and ensure compact (drops only None/"") preserves it:

```python
    if mode == "minimal":
        keep = {"mgi_id", "symbol", "match_type", "symbol_type", "match"}
        return {k: v for k, v in summary.items() if k in keep}
```

- [ ] **Step 6: Make `after_search` widen-aware.** Replace `after_search` in `next_commands.py`:

```python
def after_search(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After search_markers: open the top hit; widen if truncated."""
    hits = payload.get("results", [])
    if not hits:
        return [cmd("resolve_marker", query=query), cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = hits[0].get("mgi_id")
    if top:
        steps.append(cmd("get_marker", query=top))
    if payload.get("truncated"):
        steps.append(
            widen_cmd("search_markers", {"query": query}, int(payload.get("total", 0)), 200)
        )
    return steps or [cmd("get_server_capabilities")]
```

Update the caller in `mgi_link/mcp/tools/markers.py` `search_markers`:

```python
            payload["_meta"] = {"next_commands": after_search(query, payload)}
```

- [ ] **Step 7: Update `SEARCH_SCHEMA`** in `mgi_link/mcp/schemas.py`:

```python
SEARCH_SCHEMA = _envelope(
    query=_STR,
    marker_type=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    truncated=_BOOL,
    results=_ARR,
)
```

- [ ] **Step 8: Update the `search_markers` description** in `markers.py` to mention exact-match pinning + truncation:

Append to the description string before the `Signature:` line:
`"Exact symbol/synonym hits are pinned first (each result carries match: exact_symbol|exact_synonym|fts). Returns a truncation contract {total, returned, limit, truncated}. "`

- [ ] **Step 9: Run** `uv run pytest tests/unit/test_service.py -k search -v` and `uv run pytest tests/unit/test_tools_e2e.py -v` — fix any test asserting the removed `count` key (update to `total`/`returned`). Expect PASS.

---

### Task 3: `get_marker_phenotypes` term/genotype views (F2, F4, F5, F1-pheno)

**Files:**
- Modify: `mgi_link/services/shaping.py` (two new shapers)
- Modify: `mgi_link/services/mgi_service.py` (`get_phenotypes` dispatch, default limit 250)
- Modify: `mgi_link/mcp/next_commands.py` (`after_phenotypes` widen)
- Modify: `mgi_link/mcp/tools/phenotypes.py` (signature default + description)
- Modify: `mgi_link/mcp/schemas.py` (PHENOTYPES_SCHEMA)
- Test: `tests/unit/test_service.py`, `tests/unit/test_shaping.py`, `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Write failing tests** in `tests/unit/test_service.py`

```python
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
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_service.py -k phenotypes -v` — expect FAIL.

- [ ] **Step 3: Add shapers** to `mgi_link/services/shaping.py`:

```python
def shape_phenotype_term(row: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a distinct-term phenotype row to the requested verbosity."""
    out: dict[str, Any] = {
        "mp_id": row["mp_id"],
        "mp_term": row["mp_term"],
        "genotype_count": row["genotype_count"],
    }
    if mode == "standard":
        out["systems"] = row.get("systems", [])
    return out


def shape_phenotype_genotype(row: dict[str, Any]) -> dict[str, Any]:
    """Per-genotype phenotype row (full view): the complete annotation."""
    return row
```

- [ ] **Step 4: Rewrite `get_phenotypes`** in `mgi_link/services/mgi_service.py` (replace ~lines 233-261):

```python
    def get_phenotypes(
        self,
        query: str,
        *,
        mp_system: str | None = None,
        limit: int = 250,
        mode: str = "compact",
    ) -> dict[str, Any]:
        """Return MP annotations + phenotype summary for a marker.

        compact/standard/minimal return a deduplicated, support-ordered DISTINCT
        TERM view; full returns the per-genotype rows. ``limit`` applies to the
        unit each view emits and the truncation contract makes any cap explicit.
        """
        marker, _ = self._resolve_to_marker((query or "").strip())
        mgi_id = marker["mgi_id"]
        limit = max(1, min(limit, 1000))
        system_id = self._resolve_system(mp_system) if mp_system else None
        summary = self.repo.phenotype_summary(mgi_id)
        if mode == "full":
            total = self.repo.count_phenotype_rows(mgi_id, system_id=system_id)
            rows = self.repo.get_phenotypes(mgi_id, system_id=system_id, limit=limit)
            annotations = [shape_phenotype_genotype(r) for r in rows]
            view = "per_genotype"
        else:
            total = self.repo.count_phenotype_terms(mgi_id, system_id=system_id)
            rows = self.repo.phenotype_terms(mgi_id, system_id=system_id, limit=limit)
            annotations = [shape_phenotype_term(r, mode) for r in rows]
            view = "terms"
        return {
            "mgi_id": mgi_id,
            "symbol": marker.get("symbol"),
            "mp_system_filter": system_id,
            "view": view,
            "summary": summary,
            **page_fields(total=total, returned=len(annotations), limit=limit),
            "annotations": annotations,
        }
```

Add to the shaping imports at the top of `mgi_service.py`:

```python
from mgi_link.services.shaping import (
    shape_allele,
    shape_marker,
    shape_phenotype_genotype,
    shape_phenotype_term,
    shape_resolution,
    shape_summary,
)
```

- [ ] **Step 5: Run** `uv run pytest tests/unit/test_service.py -k phenotypes -v` — expect PASS.

- [ ] **Step 6: Make `after_phenotypes` widen-aware** in `next_commands.py`:

```python
def after_phenotypes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker_phenotypes: widen if truncated, then overview + diseases."""
    mgi_id = payload.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    if payload.get("truncated"):
        steps.append(
            widen_cmd("get_marker_phenotypes", {"query": mgi_id}, int(payload.get("total", 0)), 1000)
        )
    steps += [cmd("get_phenotype_overview", query=mgi_id), cmd("get_marker_diseases", query=mgi_id)]
    return steps
```

- [ ] **Step 7: Update tool signature default + description** in `mgi_link/mcp/tools/phenotypes.py`:

Change the `limit` default to 250:

```python
        limit: Annotated[
            int, Field(ge=1, le=1000, description="Max rows (distinct terms, or genotype rows in full mode; default 250).")
        ] = 250,
```

Replace the description body to document the two views + truncation (keep the `Signature:` line; update it to note response_mode controls the view):

```python
        description=(
            "Return the Mammalian Phenotype (MP) annotations for a mouse marker — "
            "the gene page's Phenotypes section. By default (minimal/compact/standard) "
            "returns a DEDUPLICATED, support-ordered list of DISTINCT MP terms — each "
            "{mp_id, mp_term, genotype_count} (standard adds systems[]) — so the most "
            "replicated phenotypes come first and none are buried. response_mode=full "
            "returns the per-genotype rows {mp_id, mp_term, allelic_composition, "
            "genetic_background, pubmed_id, genotype_id, ...}. Every response carries a "
            "phenotype summary and a truncation contract {total, returned, limit, "
            "truncated}; when truncated, next_commands includes a widen step. mp_system "
            "restricts to one top-level system. Annotations are single-gene genotypes "
            "(MGI_GenePheno). "
            "Signature: get_marker_phenotypes(query, mp_system=, limit=, response_mode=)."
        ),
```

- [ ] **Step 8: Update `PHENOTYPES_SCHEMA`** in `schemas.py`:

```python
PHENOTYPES_SCHEMA = _envelope(
    mgi_id=_STR,
    symbol=_STR,
    mp_system_filter=_STR_NULL,
    view=_STR,
    summary=_OBJ,
    total=_INT,
    returned=_INT,
    limit=_INT,
    truncated=_BOOL,
    annotations=_ARR,
)
```

- [ ] **Step 9: Run** `uv run pytest tests/unit/test_service.py tests/unit/test_shaping.py tests/unit/test_tools_e2e.py -v` — update any test asserting the old phenotype shape. Expect PASS.

---

### Task 4: Truncation on alleles, find-by-phenotype, mp-search (F1 remainder)

**Files:**
- Modify: `mgi_link/services/mgi_service.py` (`get_alleles`, `find_markers_by_phenotype`, `search_phenotype_terms`)
- Modify: `mgi_link/mcp/next_commands.py` (`after_alleles`, `after_find_by_pheno`, `after_search_terms` widen)
- Modify: `mgi_link/mcp/tools/alleles.py`, `ontology.py`, `phenotypes.py` (descriptions; caller signatures already pass payload)
- Modify: `mgi_link/mcp/schemas.py` (ALLELES_SCHEMA, FIND_MARKERS_SCHEMA, MP_SEARCH_SCHEMA)
- Test: `tests/unit/test_service.py`, `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Write failing tests** in `tests/unit/test_service.py`

```python
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
```

- [ ] **Step 2: Run** the three tests — expect FAIL.

- [ ] **Step 3: Wire `get_alleles`** return block in `mgi_service.py` (replace ~lines 221-229):

```python
        alleles = self.repo.get_alleles(mgi_id, allele_type=type_filter, limit=limit)
        total = sum(category_counts.values())
        shaped = [shape_allele(a, mode) for a in alleles]
        return {
            "mgi_id": mgi_id,
            "symbol": marker.get("symbol"),
            "allele_type_filter": type_filter,
            "total_alleles": total,
            "category_counts": category_counts,
            **page_fields(total=total, returned=len(shaped), limit=limit),
            "alleles": shaped,
        }
```

> Note: when `allele_type` is set, `total` from `category_counts` is the all-types total, which can exceed the filtered `returned`, mis-flagging `truncated`. Guard: when filtering, compute the filtered total instead. Replace the `total = ...` line with:

```python
        if type_filter:
            total = sum(
                n for t, n in category_counts.items() if type_filter.lower() in t.lower()
            )
        else:
            total = sum(category_counts.values())
```

- [ ] **Step 4: Wire `find_markers_by_phenotype`** return block (replace ~lines 342-351):

```python
        markers = self.repo.markers_by_phenotype(
            normalized, include_descendants=include_descendants, limit=limit
        )
        total = self.repo.count_markers_by_phenotype(
            normalized, include_descendants=include_descendants
        )
        return {
            "mp_id": normalized,
            "mp_term": term["name"],
            "include_descendants": include_descendants,
            **page_fields(total=total, returned=len(markers), limit=limit),
            "markers": markers,
        }
```

- [ ] **Step 5: Wire `search_phenotype_terms`** return block (replace ~lines 327-329):

```python
        limit = max(1, min(limit, 200))
        hits = self.repo.search_mp(raw, limit=limit)
        total = self.repo.count_mp(raw)
        return {
            "query": raw,
            **page_fields(total=total, returned=len(hits), limit=limit),
            "results": hits,
        }
```

- [ ] **Step 6: Widen-aware next_commands** in `next_commands.py`:

```python
def after_alleles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker_alleles: widen if truncated, then phenotypes/overview."""
    mgi_id = payload.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    if payload.get("truncated"):
        steps.append(
            widen_cmd("get_marker_alleles", {"query": mgi_id}, int(payload.get("total", 0)), 1000)
        )
    steps += [cmd("get_marker_phenotypes", query=mgi_id), cmd("get_phenotype_overview", query=mgi_id)]
    return steps


def after_find_by_pheno(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After find_markers_by_phenotype: widen if truncated, else open first marker."""
    markers = payload.get("markers", [])
    steps: list[dict[str, Any]] = []
    if payload.get("truncated") and payload.get("mp_id"):
        steps.append(
            widen_cmd(
                "find_markers_by_phenotype",
                {"mp_id": payload["mp_id"]},
                int(payload.get("total", 0)),
                500,
            )
        )
    if markers and markers[0].get("mgi_id"):
        steps.append(cmd("get_marker_phenotypes", query=markers[0]["mgi_id"]))
    return steps or [cmd("get_server_capabilities")]
```

> `after_search_terms` already opens the top term; leave it, but add a widen step when truncated:

```python
def after_search_terms(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After search_phenotype_terms: open the top term; widen if truncated."""
    hits = payload.get("results", [])
    if not hits:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = hits[0].get("mp_id")
    if top:
        steps.append(cmd("get_mp_term", mp_id=top))
    if payload.get("truncated"):
        steps.append(widen_cmd("search_phenotype_terms", {"query": query}, int(payload.get("total", 0)), 200))
    return steps or [cmd("get_server_capabilities")]
```

Update the `search_phenotype_terms` caller in `mgi_link/mcp/tools/ontology.py` to pass the payload:

```python
            payload["_meta"] = {"next_commands": after_search_terms(query, payload)}
```

(Check the current call signature — it likely passes `(query, payload.get("results", []))`; change to `(query, payload)`.)

- [ ] **Step 7: Update schemas** in `schemas.py`:

```python
ALLELES_SCHEMA = _envelope(
    mgi_id=_STR, symbol=_STR, allele_type_filter=_STR_NULL, total_alleles=_INT,
    category_counts=_OBJ, total=_INT, returned=_INT, limit=_INT, truncated=_BOOL, alleles=_ARR,
)

MP_SEARCH_SCHEMA = _envelope(
    query=_STR, total=_INT, returned=_INT, limit=_INT, truncated=_BOOL, results=_ARR,
)

FIND_MARKERS_SCHEMA = _envelope(
    mp_id=_STR, mp_term=_STR, include_descendants=_BOOL,
    total=_INT, returned=_INT, limit=_INT, truncated=_BOOL, markers=_ARR,
)
```

- [ ] **Step 8: Descriptions.** Append to the `get_marker_alleles`, `find_markers_by_phenotype` descriptions: `"Returns a truncation contract {total, returned, limit, truncated}; when truncated, next_commands includes a widen step. "`. For `find_markers_by_phenotype`, also append `"include_descendants defaults to true and changes WHICH genes are returned (the flag is echoed in the response). "` (covers F9).

- [ ] **Step 9: Run** `uv run pytest tests/unit/test_service.py tests/unit/test_tools_e2e.py tests/unit/test_next_commands.py -v` — update tests asserting old `count` keys. Expect PASS.

---

### Task 5: Allele-count disambiguation (F6)

**Files:**
- Modify: `mgi_link/data/repository.py` (`phenotype_summary` key `alleles` → `phenotyped_alleles`)
- Modify: `mgi_link/services/mgi_service.py` (`get_marker.summary` key `alleles` → `alleles_total`)
- Test: `tests/unit/test_service.py`, `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Write failing test** in `tests/unit/test_service.py`

```python
def test_allele_count_labels_are_explicit(service: MgiService) -> None:
    marker = service.get_marker("Wt1")
    assert "alleles_total" in marker["summary"]
    assert "alleles" not in marker["summary"]
    pheno = service.get_phenotypes("Wt1")
    assert "phenotyped_alleles" in pheno["summary"]
    assert "alleles" not in pheno["summary"]
```

- [ ] **Step 2: Run** the test — expect FAIL.

- [ ] **Step 3: Rename in `repository.phenotype_summary`** (the returned dict, ~line 256-262): change `"alleles": len(alleles),` to `"phenotyped_alleles": len(alleles),`.

- [ ] **Step 4: Rename in `mgi_service.get_marker`** summary (~lines 180-185): change `"alleles": sum(counts.values()),` to `"alleles_total": sum(counts.values()),`.

- [ ] **Step 5: Run** `uv run pytest tests/unit/test_service.py tests/unit/test_tools_e2e.py -v` — update any test/asserts referencing `summary["alleles"]`. Expect PASS.

---

### Task 6: Observability — `_meta.elapsed_ms` + diagnostics build (F10)

**Files:**
- Modify: `mgi_link/mcp/envelope.py` (`run_mcp_tool` timing; error envelope timing)
- Modify: `mgi_link/mcp/tools/discovery.py` (diagnostics build block)
- Modify: `mgi_link/mcp/schemas.py` (DIAGNOSTICS_SCHEMA)
- Test: `tests/unit/test_envelope.py`, `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Write failing test** in `tests/unit/test_tools_e2e.py`

```python
async def test_elapsed_ms_present(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("resolve_marker", {"query": "Wt1"}))
    assert isinstance(payload["_meta"]["elapsed_ms"], int)
    assert payload["_meta"]["elapsed_ms"] >= 0
    err = structured(await facade.call_tool("resolve_marker", {"query": "Zzzznotreal"}))
    assert isinstance(err["_meta"]["elapsed_ms"], int)


async def test_diagnostics_has_build(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_mgi_diagnostics", {}))
    assert "version" in payload["build"]
    assert "git_sha" in payload["build"]
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Add timing** to `run_mcp_tool` in `envelope.py`. Add `import time` at top. Wrap the body:

```python
    ctx = context or McpErrorContext(tool_name=tool_name)
    start = time.perf_counter()
    try:
        result = await call()
        if isinstance(result, dict):
            result.setdefault("success", True)
            existing_meta: dict[str, Any] = result.get("_meta") or {}
            result["_meta"] = {
                **existing_meta,
                "tool": tool_name,
                "request_id": _request_id(),
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }
        return result
    except Exception as exc:  # broad catch is the error-boundary contract
        envelope = _error_envelope(exc, ctx)
        envelope["_meta"]["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "mcp_tool_error tool=%s code=%s exc=%s",
            tool_name,
            envelope["error_code"],
            exc.__class__.__name__,
        )
        return envelope
```

- [ ] **Step 4: Add build to diagnostics.** In `discovery.py`, import `from mgi_link.buildinfo import build_info` and in `get_mgi_diagnostics`'s `call()`:

```python
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_diagnostics()
            payload["build"] = build_info()
            payload["_meta"] = {
                "next_commands": [cmd("resolve_marker", query="Wt1")]
                if payload.get("data_available")
                else [cmd("get_server_capabilities")]
            }
            return payload
```

- [ ] **Step 5: Update `DIAGNOSTICS_SCHEMA`** — add `build=_OBJ` to the `_envelope(...)` call.

- [ ] **Step 6: Run** `uv run pytest tests/unit/test_tools_e2e.py tests/unit/test_envelope.py -v` — expect PASS.

---

### Task 7: Prove the ambiguity contract (F7)

**Files:**
- Modify: `tests/fixtures/MRK_List2.rpt` (add two markers sharing a synonym) OR add to an existing synonym
- Test: `tests/unit/test_service.py`, `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Inspect the fixture** `tests/fixtures/MRK_List2.rpt` to learn the column layout and existing rows (`Read` it). Identify two real markers, or add a second marker whose synonym collides with an existing one. Pick a synonym token not already unique-resolvable.

- [ ] **Step 2: Write failing test** in `tests/unit/test_service.py`

```python
def test_ambiguous_symbol_raises_with_candidates(service: MgiService) -> None:
    from mgi_link.exceptions import AmbiguousQueryError

    with pytest.raises(AmbiguousQueryError) as exc:
        service.resolve("<AMBIGUOUS_SYN>")  # shared synonym in the fixture
    assert len(exc.value.candidates) >= 2
```

And e2e in `tests/unit/test_tools_e2e.py`:

```python
async def test_ambiguous_query_envelope(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("resolve_marker", {"query": "<AMBIGUOUS_SYN>"}))
    assert payload["success"] is False
    assert payload["error_code"] == "ambiguous_query"
    assert len(payload["candidates"]) >= 2
    assert payload["_meta"]["next_commands"][0]["tool"] == "get_marker"
```

- [ ] **Step 3: Run** — expect FAIL (currently resolves or not-found).

- [ ] **Step 4: Edit the fixture** so one synonym maps to two markers with the same `symbol_type` (both `synonym`). Add a minimal second marker row to `MRK_List2.rpt` carrying the shared synonym. Replace `<AMBIGUOUS_SYN>` in the tests with the chosen token.

- [ ] **Step 5: Run** the two tests — expect PASS. The production resolver is unchanged; the fixture now exercises the live `_ambiguity_error` path. Confirm no other fixture-based test regressed (`uv run pytest -q`).

---

### Task 8: Capabilities honesty, behavioural docs, version bump (F5, F8, F9)

**Files:**
- Modify: `mgi_link/mcp/capabilities.py` (`response_mode_semantics`, `behavioral_defaults`, `truncation_contract`, `field_glossary`, summary keys)
- Modify: `mgi_link/mcp/resources.py` (reference notes: truncation + glossary)
- Modify: `mgi_link/__init__.py` (`__version__` → 0.2.0)
- Modify: `mgi_link/mcp/tools/markers.py` (resolve_marker description: human-collision note)
- Test: `tests/unit/test_tools_e2e.py`

- [ ] **Step 1: Write failing test** in `tests/unit/test_tools_e2e.py`

```python
async def test_capabilities_documents_new_contracts(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_server_capabilities", {"detail": "full"}))
    assert "truncation_contract" in payload
    assert "response_mode_semantics" in payload
    assert "behavioral_defaults" in payload
    assert "field_glossary" in payload
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: Add blocks to `build_capabilities()`** in `capabilities.py` (inside the returned dict):

```python
        "truncation_contract": (
            "Every list tool returns total (matches before the cap), returned (rows "
            "in this payload), limit (cap applied), and truncated (total > returned). "
            "When truncated is true, _meta.next_commands includes a ready-to-call "
            "widen step that raises limit. Never infer completeness from list length."
        ),
        "response_mode_semantics": {
            "get_marker_phenotypes": (
                "minimal/compact/standard = deduplicated, support-ordered DISTINCT "
                "term list ({mp_id, mp_term, genotype_count}; standard adds systems[]); "
                "full = per-genotype rows with allelic composition, background, PubMed."
            ),
            "get_marker": (
                "minimal = identity anchors; compact = drops null/verbose "
                "(cm_position/status); standard/full = the complete record."
            ),
            "search_markers/get_marker_alleles": (
                "minimal trims to identity; compact drops null/empty; standard/full "
                "return the full rows."
            ),
        },
        "behavioral_defaults": {
            "find_markers_by_phenotype.include_descendants": (
                "Defaults to true: child (more specific) MP terms are rolled up via "
                "the ontology, so the gene set is broader than exact-term-only. The "
                "flag is echoed in every response."
            ),
            "get_marker_phenotypes.default_view": (
                "compact term view (default limit 250) returns all distinct terms for "
                "a typical gene; pass response_mode=full for per-genotype detail."
            ),
            "resolve_marker.human_symbol_collision": (
                "A human symbol identical (case-insensitively) to the mouse symbol "
                "resolves via the mouse symbol with match_type=current rather than "
                "ortholog; the resolved marker is the same correct mouse marker."
            ),
        },
        "field_glossary": {
            "alleles_total": "get_marker.summary: all phenotypic alleles of the marker.",
            "total_alleles": "get_marker_alleles: all phenotypic alleles (same population as alleles_total).",
            "phenotyped_alleles": "phenotype summary: distinct alleles appearing in MP annotations (a subset).",
            "genotype_count": "get_marker_phenotypes term view: distinct genotypes supporting that MP term.",
            "match": "search_markers hit: exact_symbol | exact_synonym | fts.",
        },
```

Add the four keys to `_SUMMARY_KEYS` so the default (summary) detail also exposes them: append `"truncation_contract"`, `"response_mode_semantics"`, `"behavioral_defaults"`, `"field_glossary"`.

- [ ] **Step 4: Reference notes.** In `resources.py`, append to `MGI_REFERENCE_NOTES`: a sentence describing the truncation contract and the allele-count glossary (`alleles_total` vs `phenotyped_alleles`).

- [ ] **Step 5: resolve_marker description** in `markers.py`: append before `Signature:`: `"A human symbol identical to the mouse symbol resolves as match_type=current (case collision) rather than ortholog; the marker is the same. "` (covers F8).

- [ ] **Step 6: Version bump.** `mgi_link/__init__.py`: `__version__ = "0.2.0"`.

- [ ] **Step 7: Run** `uv run pytest tests/unit/test_tools_e2e.py -v` — expect PASS.

---

### Task 9: Schema sweep, evaluation addendum, full verification

**Files:**
- Modify: `MCP_EVALUATION.md` (remediation addendum)
- Verify: whole suite + live re-probe

- [ ] **Step 1: Self-review the schema file** `schemas.py` — confirm every modified tool's schema includes the new fields (search, alleles, phenotypes, find_markers, mp_search, diagnostics). Permissive `additionalProperties` means tests still pass, but declared fields aid clients.

- [ ] **Step 2: Run the full unit suite** `make test-fast` (or `uv run pytest tests/unit -q`). Fix every failure (mostly renamed keys: `count` → `total`/`returned`, `summary["alleles"]`).

- [ ] **Step 3: Run** `make ci-local` — must be green (format-check, lint-ci, lint-loc, typecheck, test-fast). Fix line-budget violations by extracting helpers if any file exceeds 500 lines (likely candidates: `repository.py`, `mgi_service.py`, `next_commands.py`).

- [ ] **Step 4: Live re-probe** against the real index. Run the server's repository directly with a tiny script (or via the live MCP) and confirm:
  - `get_marker_phenotypes("Pkd1")` default: `view == "terms"`, `truncated` present, and the annotations include `polycystic kidney` (MP:0008528) and `kidney cyst`.
  - `search_markers("Pax6")`: `results[0].symbol == "Pax6"`, `match == "exact_symbol"`.
  - `find_markers_by_phenotype("MP:0008528", limit=10)`: `total` >> 10, `truncated` true, widen step in next_commands.

```bash
uv run python - <<'PY'
from mgi_link.data.repository import MgiRepository
from mgi_link.services.mgi_service import MgiService
svc = MgiService(MgiRepository("data/mgi.sqlite"))
ph = svc.get_phenotypes("Pkd1", mode="compact")
terms = {a["mp_term"] for a in ph["annotations"]}
print("view", ph["view"], "total", ph["total"], "returned", ph["returned"], "truncated", ph["truncated"])
print("polycystic kidney present:", "polycystic kidney" in terms)
print("kidney cyst present:", "kidney cyst" in terms)
s = svc.search("Pax6", limit=25)
print("top:", s["results"][0]["symbol"], s["results"][0]["match"], "total", s["total"])
f = svc.find_markers_by_phenotype("MP:0008528", limit=10)
print("find total", f["total"], "returned", f["returned"], "truncated", f["truncated"])
PY
```

Expected: polycystic kidney present True, kidney cyst present True, top Pax6 exact_symbol, find total >> 10 truncated True.

- [ ] **Step 5: Append the remediation addendum** to `MCP_EVALUATION.md` — a short section mapping F1–F10 to the implemented fix and the new contracts, with a closing note on the expected grade lift.

- [ ] **Step 6: Final `make ci-local`** — green. Done.

---

## Self-Review

**Spec coverage:** F1→Tasks 1,2,3,4 (contract everywhere); F2→Task 3 (term view + ordering); F3→Task 2 (exact boost); F4→Task 3 (dedup minimal); F5→Tasks 3,8 (view tiers + semantics doc); F6→Task 5 (label rename); F7→Task 7 (fixture+test); F8→Task 8 (resolve doc); F9→Tasks 4,8 (include_descendants doc); F10→Task 6 (elapsed_ms + build). All ten covered.

**Type consistency:** `page_fields(total=, returned=, limit=)` keyword-only, used identically in service search/alleles/phenotypes/find/mp. `widen_cmd(tool, base_args, total, ceiling)` used in after_search/after_phenotypes/after_alleles/after_find_by_pheno/after_search_terms. `after_search`/`after_search_terms` both take `(query, payload)` — callers updated in markers.py/ontology.py. Shapers: `shape_phenotype_term(row, mode)`, `shape_phenotype_genotype(row)`.

**Placeholders:** none except `<AMBIGUOUS_SYN>` in Task 7, resolved against the real fixture during execution (explicitly called out as a fixture-inspection step).

**Budget watch:** repository.py (+~70 lines) and mgi_service.py (+~20) and next_commands.py (+~25) may approach 500; Task 9 Step 3 mandates an extract-on-overflow fix.
