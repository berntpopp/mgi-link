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

**Gene-only limitation.** The live path resolves InterMine `Gene` records only.
Non-gene markers (QTL, transgene, complex, cytogenetic marker) are not resolvable
while the index is cold — they return the normal `not_found`. The overwhelming
majority of resolve/get_marker queries target genes; full non-gene parity (an
InterMine `SequenceFeature` query) is deferred (§8). This limitation is
documented in capabilities.

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

**The provider is passed explicitly, never swapped globally.**
`_resolve_to_marker(raw)` becomes `_resolve_to_marker(raw, provider)`. Only the
two identity tools (`resolve`, `get_marker`) pass the fallback-aware provider
(`self._provider`); the five aggregate tools that also resolve first
(`get_alleles`, `get_phenotypes`, `get_phenotype_overview`, `get_diseases`,
`get_ortholog`) pass `self.repo`, so when cold they fail fast with
`data_unavailable` **without** issuing a wasted MouseMine call. This is what keeps
the fallback strictly identity-only.

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

**Marker dict mapping.** The client returns the exact keys
`repository.get_marker` returns, sourced from `constants.MARKER_SCALAR_FIELDS`
(`mgi_id`, `symbol`, `name`, `marker_type`, `feature_type`, `chromosome`,
`cm_position`, `coord_start`, `coord_end`, `strand`, `status`, `entrez_id`,
`ensembl_gene_id`, **`refseq_id`**) plus `symbol_upper` (derived from `symbol`)
and `synonyms` (list). The xref key is `refseq_id` — **not** `refseq`. Fields
MouseMine does not return for a given gene are `None`/`[]` — never fabricated.

**Class scope.** All four queries target the InterMine `Gene` class (per §2's
gene-only limitation); the homologue paths use `Gene.homologues.homologue`.

**De-duplication.** A live MouseMine probe confirms multi-valued joins (synonyms,
homologues, xrefs) return **repeated outer rows** — e.g. `Wt1` yields one row per
synonym×homologue combination. The client MUST aggregate rows by
`primaryIdentifier`: collapse to one marker, collect `synonyms` into a de-duped
list, and pick a single ortholog (or the first homologue). `lookup_symbol`
de-dupes `(mgi_id, symbol_type)` pairs so the ambiguity count reflects distinct
markers, not join cardinality.

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

**The live path is additive only — the index path is byte-identical to v0.2.0.**
Provenance markers appear *only* when the fallback served the response; a
repo-backed response is unchanged (no `source`, no `partial`). Absence of
`_meta.source` therefore means "index". This preserves the default invariant
(`enable_live_fallback=False` ⇒ no behavioral change whatsoever).

When the fallback serves a response:
- `resolve_marker` and `get_marker` carry `_meta.source = "mousemine"`.
- Live `get_marker` returns identity + location + xrefs + human ortholog but
  **omits the `summary` block** (alleles/phenotypes/diseases counts require index
  aggregation) and carries `_meta.partial = true` plus a short note that counts
  and the allele/phenotype tools require the built index.
- `resolve_marker` is full-fidelity live (identity/provenance only).

**How the MCP layer learns the source (thread-safe, no service side-effect).**
"Services return plain dicts; the MCP layer owns `_meta`" is preserved. The
service includes plain top-level keys `source` (and, for `get_marker`, `partial`)
in its returned dict **only on the live path**. Each tool's `call()` pops those
keys off the body and lifts them into `_meta` (alongside `elapsed_ms`/`tool` from
the v0.2.0 remediation). Because the values travel inside the per-call return
value — never stored on the shared singleton — concurrent requests cannot race on
a "last source" field.

## 6. Wiring

- `MgiService.__init__(self, repository, fallback=None)` — accepts an optional
  `MarkerProvider`. A `_provider` property returns `self._repo` if present, else
  `self._fallback`; raises `DataUnavailableError` only when **both** are absent.
  A `using_fallback` property (`self._repo is None and self._fallback is not None`)
  tells `resolve`/`get_marker` whether to stamp `source`/`partial` on the return
  dict.
- `_resolve_to_marker(raw, provider)` takes the provider explicitly. `resolve`
  and `get_marker` pass `self._provider`; the five aggregate tools pass
  `self.repo` (fail-fast `data_unavailable` while cold, no MouseMine call).
- `get_marker`: the `summary` block is built only when the resolving provider is
  the repository; with the fallback provider it is omitted and the returned dict
  carries `partial = true` (lifted to `_meta` per §5).
- **Source-aware next_commands.** `after_resolve`/`after_get_marker` read the
  payload's `source`. When `"mousemine"`, the index-only chains are replaced:
  `after_resolve` → `get_marker(mgi_id)` only; `after_get_marker` →
  `get_mgi_diagnostics` + `get_server_capabilities` (never the cold
  `get_marker_phenotypes`/`get_marker_alleles`/`get_phenotype_overview`). The
  index path's chains are unchanged.
- `service_adapters._build_service()`: when `settings.mousemine.enable_live_fallback`,
  construct a `MouseMineClient(settings.mousemine)` and pass it as `fallback` to
  `MgiService`. When disabled, `fallback=None` (today's behavior exactly).
- **Client lifecycle.** `MouseMineClient.close()` closes the underlying
  `httpx.Client`; `MgiService.close()` closes its fallback if present.
  `reset_mgi_service()` and `set_mgi_service()` close the previously cached
  service before dropping it, so the index-refresh swap and test teardown do not
  leak connections.
- `get_mgi_diagnostics` reports `live_fallback: {"enabled": bool, "base_url": str}`.
- `capabilities.behavioral_defaults` documents the cold-start fallback (which
  tools, the enable flag, the gene-only limitation, the `_meta.source`/`partial`
  markers).

## 7. Testing (TDD, respx)

- **`tests/unit/test_mousemine.py`** (new): respx-mock the InterMine JSON
  endpoint. Assert each of the four methods maps a canned PathQuery JSON response
  to the correct dict (`refseq_id` key present, `synonyms` a list); the
  human→ortholog homologue path; **duplicate join rows collapse to one marker
  with a de-duped synonym list** (the Wt1 repeated-row case); a `Gene` query for a
  non-gene id → no marker; an empty result → no marker; 429 → `RateLimitError`;
  5xx-after-retries → `ServiceUnavailableError`; retry actually re-issues;
  rate-limiter throttles; `close()` closes the client.
- **`tests/unit/test_service.py`** (extend): a fake `MarkerProvider`
  (no network) injected as `MgiService(None, fallback=fake)`. Assert
  `resolve`/`get_marker` return index-shaped dicts with `source == "mousemine"`;
  the ambiguity contract still fires; `get_marker` omits `summary` and sets
  `partial`; `get_marker_alleles`/`get_marker_phenotypes` still raise
  `DataUnavailableError` **without** the fake provider being called (assert
  fail-fast — the fake records zero invocations).
- **`tests/unit/test_tools_e2e.py`** (extend): with a fallback-backed service,
  `resolve_marker`/`get_marker` envelopes carry `_meta.source == "mousemine"`,
  `get_marker` carries `_meta.partial`, and `source`/`partial` are **absent from
  the answer body**; `_meta.next_commands` are source-aware (no
  `get_marker_phenotypes`/`get_marker_alleles`). With a **repo-backed** service,
  assert `_meta` has **no** `source` key (byte-identical default). With no
  provider and no fallback, both identity tools return `data_unavailable`.
- **`tests/unit/test_config.py`**: `enable_live_fallback` default `False`; the
  `user_agent` property shape.
- Gate: `make ci-local` green (format, lint, 500-line budget, mypy strict, tests).
  `mousemine.py` is a new focused file, comfortably within the 500-line budget.

## 8. Out of scope (YAGNI / v2)

Live fallback for the aggregate tools (alleles, phenotypes, overview, diseases,
ortholog-as-a-tool, MP ontology, search, reverse phenotype lookup); live
resolution of **non-gene markers** (QTL/transgene/complex via an InterMine
`SequenceFeature` query); per-lookup "miss" enrichment while the index is warm;
async conversion of the service layer; caching live MouseMine responses; Alliance
Genome HGVS enrichment.
