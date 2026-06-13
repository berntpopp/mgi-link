# mgi-link — MouseMine Cold-Start Fallback Design

**Date:** 2026-06-13
**Status:** Approved (autonomous implementation)
**Author:** Claude (MCP engineering)
**Target:** Implement the optional live MouseMine fallback declared in the base
design spec (`2026-06-12-mgi-link-design.md` §2/§4) but deferred at v0.2.0 — the
one design-spec item with config scaffolding (`MouseMineConfig`) but no client.

---

## 1. Problem statement

The base design specifies an optional **live MouseMine (InterMine) fallback** so
the server stays useful before the offline SQLite index is built. At v0.2.0 the
config (`MouseMineConfig`: `base_url`, `rate_limit_per_s`, `max_retries`,
`timeout`, `enable_live_fallback=False`) exists, but there is no client
(`mgi_link/api/mousemine.py`) and no wiring. Today, when the index is cold
(`_repo is None` — not built, building, or corrupt), **every** tool raises
`DataUnavailableError` → `data_unavailable`.

This closes that gap with the smallest high-value slice: a **cold-start safety
net** for the two identity tools, `resolve_marker` and `get_marker`.

## 2. Scope

**In scope.** A live path for `resolve_marker` and `get_marker` that activates
**only** when both hold:

1. the local index is unavailable (`_repo is None`), **and**
2. `mousemine.enable_live_fallback=True` (default `False`).

The live resolver has **full input parity** with the index resolver: MGI id,
current mouse symbol, synonym, **and** human gene symbol → mouse ortholog (via an
InterMine homologue query).

**Out of scope (unchanged while cold → `data_unavailable`).**
`search_markers`, `get_marker_alleles`, `get_marker_phenotypes`,
`get_phenotype_overview`, `get_marker_diseases`, `get_marker_ortholog`,
`get_mp_term`, `search_phenotype_terms`, `find_markers_by_phenotype`. These need
aggregate/closure data that a cold-start net should not re-implement live.

**Invariant preserved.** When the index is present, MouseMine is **never**
touched — lookups stay deterministic, fast, and offline. With the default
config (`enable_live_fallback=False`) behavior is byte-identical to v0.2.0.

## 3. Architecture — narrow "marker provider"

`resolve`/`get_marker` already depend on exactly four repository methods. Define
a `MarkerProvider` Protocol over precisely those:

```python
class MarkerProvider(Protocol):
    def get_marker(self, mgi_id: str) -> dict[str, Any] | None: ...
    def lookup_symbol(self, raw: str) -> list[tuple[str, str]]: ...      # [(mgi_id, "current"|"synonym")]
    def lookup_by_xref(self, source: str, value: str) -> list[str]: ...  # [mgi_id]
    def get_ortholog(self, mgi_id: str) -> dict[str, Any] | None: ...
```

`MgiRepository` already satisfies it. `MouseMineClient` implements the same four
methods, returning **identical dict shapes**, so the existing resolution cascade
(id → current symbol → synonym → human ortholog) and the ambiguity contract run
unchanged against whichever provider is live.

**Alternatives rejected.** (B) Parallel `*_live` methods duplicate the resolution
cascade in two places. (C) Fallback inside the repository puts network I/O in the
SQLite read layer, breaking the data-plane/network layering.

## 4. `mgi_link/api/mousemine.py` — `MouseMineClient`

Synchronous `httpx.Client` (matches `ingest/downloader.py`; the whole service
layer is sync). Talks to the InterMine PathQuery JSON web service:
`GET {base_url}/query/results?query=<PathQuery XML>&format=json`.

| Method | InterMine query | Returns |
|---|---|---|
| `get_marker(mgi_id)` | `Gene` constrained by `primaryIdentifier = mgi_id`; views: symbol, name, type, chromosome, GRCm39 start/end/strand, synonyms, RefSeq/Ensembl/Entrez xrefs | marker dict (same keys `repository.get_marker` returns) or `None` |
| `lookup_symbol(raw)` | `Gene` where `symbol = raw` (→ `current`) unioned with synonym match (→ `synonym`), case-insensitive | `[(mgi_id, symbol_type)]`, `current` ranked first |
| `lookup_by_xref(source, value)` | human `Gene` (symbol/HGNC) → `homologues.homologue` mouse `Gene.primaryIdentifier` | `[mgi_id]` |
| `get_ortholog(mgi_id)` | mouse `Gene` → `homologues.homologue` human `Gene` symbol/HGNC/Entrez/Ensembl/OMIM | ortholog dict (`human_symbol`, `hgnc_id`, `human_entrez`, `human_ensembl`, `omim_gene_id`) or `None` |

**Marker dict mapping.** The client returns the subset of `marker`-table columns
that `resolve`/`get_marker` consume: `mgi_id`, `symbol`, `symbol_upper`, `name`,
`marker_type`, `feature_type`, `chromosome`, `coord_start`, `coord_end`,
`strand`, `synonyms` (list), `refseq`, `ensembl_gene_id`, `entrez_id`. Fields
MouseMine does not return for a given gene are `None`/`[]` — never fabricated.

**Resilience.** Token-bucket rate limit at `rate_limit_per_s`; retry on
429/5xx/network up to `max_retries` (exponential backoff); per-request `timeout`;
`User-Agent` from `MouseMineConfig.user_agent`. Mapping to the 7-code taxonomy:
- HTTP 429 → `RateLimitError` → `rate_limited`
- HTTP 5xx / connect/read timeout / transport error (after retries) →
  `ServiceUnavailableError` → `upstream_unavailable`
- A well-formed empty result is **not** an error — it maps to the resolver's
  normal `not_found` path (no marker), identical to an index miss.

The ambiguity contract is preserved: when `lookup_symbol` returns ≥2 markers
sharing the same best `symbol_type`, the service raises `AmbiguousQueryError`
exactly as it does for the index.

## 5. Provenance & response shape

- Every response gains `_meta.source`: `"index"` for repo-backed,
  `"mousemine"` for live.
- Live `get_marker` returns identity + location + xrefs + human ortholog but
  **omits the `summary` block** (alleles/phenotypes/diseases counts require index
  aggregation) and sets `_meta.partial = true` with a short note that counts and
  the allele/phenotype tools require the built index.
- `resolve_marker` is full-fidelity live (it returns identity/provenance only),
  differing from the index path only by `_meta.source`.

`_meta.source` is set in the MCP tool/envelope layer (volatile telemetry stays
namespaced under `_meta`, never in the grounded answer) — consistent with the
`elapsed_ms` placement from the v0.2.0 remediation.

## 6. Wiring

- `MgiService.__init__(self, repository, fallback=None)` — accepts an optional
  `MarkerProvider`. A `_provider` property returns `self._repo` if present, else
  `self._fallback`; raises `DataUnavailableError` only when **both** are absent.
- `_resolve_to_marker` and `get_marker` switch from `self.repo` to
  `self._provider`. Methods outside scope keep using `self.repo`, so they still
  raise `data_unavailable` while cold.
- `get_marker`: the `summary` block is built only when the live provider is the
  repository; with the fallback provider it is omitted and `partial` is flagged.
- `service_adapters._build_service()`: when `settings.mousemine.enable_live_fallback`,
  construct a `MouseMineClient(settings.mousemine)` and pass it as `fallback` to
  `MgiService`. When disabled, `fallback=None` (today's behavior exactly).
- `get_mgi_diagnostics` reports `live_fallback: {"enabled": bool, "base_url": str}`.
- `capabilities.behavioral_defaults` documents the cold-start fallback (which
  tools, the enable flag, the `_meta.source`/`partial` markers).

## 7. Testing (TDD, respx)

- **`tests/unit/test_mousemine.py`** (new): respx-mock the InterMine JSON
  endpoint. Assert each of the four methods maps a canned PathQuery JSON response
  to the correct dict; the human→ortholog homologue path; an empty result → no
  marker; 429 → `RateLimitError`; 5xx-after-retries → `ServiceUnavailableError`;
  retry actually re-issues; rate-limiter throttles.
- **`tests/unit/test_service.py`** (extend): a fake `MarkerProvider`
  (no network) injected as `MgiService(None, fallback=fake)`. Assert
  `resolve`/`get_marker` return index-shaped dicts; the ambiguity contract still
  fires; `get_marker` omits `summary`; `get_marker_alleles`/`get_marker_phenotypes`
  still raise `DataUnavailableError`.
- **`tests/unit/test_tools_e2e.py`** (extend): with a fallback-backed service,
  `resolve_marker`/`get_marker` envelopes carry `_meta.source == "mousemine"` and
  `get_marker` carries `_meta.partial`; with no provider and no fallback, both
  return `data_unavailable`.
- **`tests/unit/test_config.py`**: `enable_live_fallback` default `False`; the
  `user_agent` property shape.
- Gate: `make ci-local` green (format, lint, 500-line budget, mypy strict, tests).
  `mousemine.py` is a new focused file, comfortably within the 500-line budget.

## 8. Out of scope (YAGNI / v2)

Live fallback for the aggregate tools (alleles, phenotypes, overview, diseases,
ortholog-as-a-tool, MP ontology, search, reverse phenotype lookup); per-lookup
"miss" enrichment while the index is warm; async conversion of the service layer;
caching live MouseMine responses; Alliance Genome HGVS enrichment.
