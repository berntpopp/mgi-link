# mgi-link MCP — Evaluation Remediation Design

**Date:** 2026-06-12
> Historical record

**Author:** MCP engineering (remediation of `MCP_EVALUATION.md`)
**Status:** Approved for implementation (autonomous end-to-end execution)
**Target:** Lift the live black-box grade from **B+ (7.5/10)** to **>9.5/10** by closing
all ten findings (F1–F10), prioritising grounding safety.

---

## 1. Problem statement

`MCP_EVALUATION.md` graded the server B+ (7.5/10). The contract layer (envelope,
error taxonomy, discovery, aliasing) is excellent and must be preserved. The
weaknesses are concentrated in the highest-traffic tools and are dominated by one
class of failure: **silent truncation** — payloads that look complete but are not.
For a faithful-grounding server this is the worst failure mode because it produces
confident wrong answers instead of visible errors.

### Findings reproduced live (release Mon 08 Jun 2026, real 384 MB index)

| ID | Severity | Reproduced fact |
|----|----------|-----------------|
| F1 | HIGH | `find_markers_by_phenotype(MP:0008528, limit=10)` → `count:10`, **no total**. `get_marker_phenotypes(Pkd1)` → `returned:100` vs `summary.phenotypes:126`, **no `truncated`**. |
| F2 | HIGH | `get_marker_phenotypes(Pkd1)` is ordered **alphabetically**, cut at "enlarged kidney" (100th). `kidney cyst` and `polycystic kidney` — the defining phenotypes — are silently dropped. Recovery `next_commands` point at tools that do not return the dropped rows. |
| F3 | HIGH | `search_markers("Pax6")` returns 25 hits and the canonical **Pax6 gene (MGI:97490) is absent entirely** — outranked by a chromosomal deletion (12.26), `Paupar` lncRNA (10.70), `Pax6os1` lncRNA (8.75), and many transgenes. `resolve_marker("Pax6")` resolves it fine, proving the data is present; only ranking is wrong. |
| F4 | MED | `get_marker_phenotypes(Pkd1, minimal)` keeps row duplication: `edema` ×9, `enlarged kidney` ×7. Dupes burn the truncation budget, so fewer *distinct* terms survive. |
| F5 | MED | `response_mode` largely inert: for `get_marker_phenotypes`, `compact == standard == full`; only `minimal` differs. Four modes advertised, ~2 distinct outputs. |
| F6 | MED | "alleles" means three populations: `get_marker.summary.alleles=46` (all), `get_marker_phenotypes.summary.alleles=28` (phenotyped), `get_marker_alleles.total_alleles=46` (all). Same label, different denominators. |
| F7 | LOW | `ambiguous_query` never observed; contract is documented but unproven by any regression fixture. |
| F8 | LOW | Human input match_type is collision-dependent: `NAA10→ortholog`, `BRCA2→current` (case-collision with mouse `Brca2`). Undocumented. |
| F9 | LOW | `include_descendants=true` default changes *which* genes return; under-advertised. |
| F10 | LOW | No `_meta.elapsed_ms` anywhere (observability 6/10); `build.git_sha` shows `unknown` and is absent from `get_mgi_diagnostics`. |

---

## 2. Design principles (preserve these invariants)

Per `AGENTS.md` and the best-practice research (Anthropic "Writing effective tools
for agents"; MCP pagination spec; MCP Toolbox style guide):

- Services return plain dicts; the MCP layer owns the envelope. No exceptions.
- Every response keeps `_meta.next_commands`, the 7-code error taxonomy, every
  tool's `output_schema`, mypy strict, 500-line/file budget, `make ci-local` green.
- **Truncation must be explicit and self-describing** — an LLM must never be able
  to mistake a capped list for a complete one. Steer recovery via `next_commands`.
- **High-signal first** — exact matches outrank substring/FTS noise.
- Token efficiency via genuine, documented `response_mode` tiers; dedupe before
  serialising. Volatile telemetry is namespaced under `_meta`, never in the answer.

---

## 3. The truncation contract (F1) — uniform across every list tool

Add four canonical, flat keys to **every list-returning tool** (`search_markers`,
`get_marker_alleles`, `get_marker_phenotypes`, `find_markers_by_phenotype`,
`search_phenotype_terms`):

```jsonc
{
  "total":     412,   // true number of items matching the query, BEFORE the cap
  "returned":  100,   // items actually in this payload
  "limit":     100,   // the cap applied (post-clamp)
  "truncated": true   // total > returned — never inferred from len()
}
```

Rules:
- `truncated == (total > returned)`, computed server-side.
- When `truncated`, the tool's `next_commands` MUST include a **widen** step: the
  same call with `limit` raised to fit (`min(total, ceiling)`), so recovery is a
  single ready-to-call step rather than guesswork.
- Existing domain totals stay for continuity: `get_marker_alleles` keeps
  `total_alleles` (already the true total) and additionally exposes the canonical
  `total`/`truncated`/`limit`. The misleading bare `count` field on
  `search_markers` / `find_markers_by_phenotype` / `search_phenotype_terms` is
  **replaced** by the four canonical keys (a clean break at v0.x).

Implementation: a tiny pure helper `services/pagination.py::page_fields(total,
returned, limit) -> dict` and `next_commands.py::widen_cmd(tool, arguments, total,
ceiling)`. Repository gains cheap `COUNT` methods for the two tools whose true
total is not already computed (search, find-by-phenotype, mp-search).

---

## 4. `get_marker_phenotypes` redesign (F2, F4, F5) — the core fix

Root cause: the tool emits **one row per genotype**, ordered **alphabetically by
term**, then caps at `limit`. So 126 distinct phenotypes explode into hundreds of
near-duplicate rows, and the cap drops whatever sorts late — regardless of clinical
salience. This is the single most important fix in the evaluation.

### New tiered model

Two genuinely different shapes, selected by `response_mode`:

**A. Term-level view — `minimal` / `compact` / `standard` (the new default family).**
One entry per **distinct MP term**, deduplicated, ordered by **support
(`genotype_count` desc, then term asc)** so the most-replicated phenotypes surface
first and salient terms are never buried by alphabet.

| mode | per-term fields |
|------|-----------------|
| `minimal` | `{mp_id, mp_term, genotype_count}` |
| `compact` | `{mp_id, mp_term, genotype_count}` (default) |
| `standard` | `{mp_id, mp_term, genotype_count, systems[]}` — the top-level MP system(s) the term rolls up to |

The single `limit` parameter applies to **the unit each view emits** — distinct
terms for the term-level family, genotype rows for `full`. Its **default is raised
from 100 to 250** (ceiling 1000) so a typical gene returns *all* its distinct terms
in one compact call. Because a term row is tiny, this is a net token *reduction*
versus today's 100 verbose genotype rows. Pkd1's 126 distinct terms — including
`polycystic kidney` and `kidney cyst` — all fit in the default `compact` call.
`total` = distinct-term count (= `summary.phenotypes`); `truncated` fires only for
the rare hyper-annotated gene, and support ordering guarantees the *least*-supported
tail terms drop, never the defining ones.

**B. Per-genotype view — `full`.**
The current rich rows `{mp_id, mp_term, allelic_composition, allele_symbols,
allele_ids, genetic_background, pubmed_id, genotype_id}`, ordered by
`(term asc, genotype_id)`. The same `limit` (default 250) now applies to genotype
rows; `total` = total row count; the truncation contract applies. This preserves
every byte of today's detail for callers that need provenance, now as an explicit
opt-in.

### Why this resolves three findings at once
- **F2**: salience ordering + a default limit that fits all distinct terms ⇒ the
  defining phenotypes are present in the default response; any truncation is
  explicit and drops only low-support tail terms.
- **F4**: the default family is deduplicated by construction; `minimal` becomes the
  5–8× token win it was meant to be (`edema` once with `genotype_count: 9`).
- **F5**: `compact`/`standard`/`full` now produce materially different shapes, and
  the deltas are documented in capabilities (§8).

`summary` is unchanged except the allele key rename in §7.

---

## 5. `search_markers` exact-match boosting (F3)

Tiered ranking in the repository search layer:

1. **exact current-symbol** match (`marker_lookup.symbol_type='current'`, uppercased equality)
2. **exact synonym** match (`marker_lookup.symbol_type='synonym'`)
3. **FTS** relevance (current behaviour), with exact hits removed to avoid dupes.

Exact hits are pinned ahead of FTS hits regardless of bm25 score. Each result
gains a `match` field — `"exact_symbol" | "exact_synonym" | "fts"` — so the LLM can
trust hit #1 without reasoning about opaque scores (mirrors `resolve_marker`'s
`match_type` vocabulary). `search_markers("Pax6")` then returns the Pax6 gene
(MGI:97490) at rank 1 with `match: "exact_symbol"`. The existing `after_search`
chain already targets `hits[0]`, so it self-corrects to the right marker.

`marker_type` filtering and `limit` clamping are applied after the merge so an
exact hit still respects the filter. `total` counts the merged, de-duplicated set.

---

## 6. Ambiguity contract proof (F7)

The resolver only raises `AmbiguousQueryError` when one uppercased lookup symbol
maps to ≥2 markers sharing the same best `symbol_type`. The evaluation never
triggered it, leaving the documented candidate-list contract unproven.

Fix: add a deterministic **fixture** (two markers sharing one synonym) and tests
asserting (a) `resolve_marker` raises `ambiguous_query` with a populated
`candidates` list, and (b) the error envelope's `next_commands` point at each
candidate via `get_marker`. This proves the contract is live code, not dead
documentation. No production-logic change — the path already exists and is correct.

---

## 7. Allele-count disambiguation (F6)

Make the denominator explicit everywhere the count appears:

- `phenotype_summary` (used by `get_marker_phenotypes` and `get_phenotype_overview`):
  rename `alleles` → **`phenotyped_alleles`**.
- `get_marker.summary`: rename `alleles` → **`alleles_total`** (and keep
  `phenotypes`, `phenotype_references`, `diseases`).
- `get_marker_alleles`: keep `total_alleles` (already unambiguous).

Same concept, three call sites, now three self-describing labels that can never be
silently summed into a wrong number. Capabilities documents the glossary.

---

## 8. `response_mode` honesty + behavioural docs (F5, F8, F9)

Add a `response_mode_semantics` block to `build_capabilities()` describing, per
tool family, what each mode includes (e.g. "get_marker_phenotypes: compact/standard
= deduplicated term list; full = per-genotype rows"). This makes the four-mode
advertisement honest rather than forcing artificial differences on tools where two
tiers genuinely suffice.

Document the two behavioural defaults the evaluation flagged:
- **F9**: `include_descendants=true` — already in the tool description; add an
  explicit `behavioral_defaults` note in capabilities and echo the flag in the
  response (already returned) so its effect on *which* genes appear is visible.
- **F8**: a human symbol identical (case-insensitively) to the mouse symbol
  resolves via the mouse symbol with `match_type=current` (the marker is identical
  to the ortholog path; only the provenance label differs). Document under
  `match_type` notes; no logic change (the resolved marker is correct either way).

---

## 9. Observability (F10)

- **`_meta.elapsed_ms`** on every response: measure wall time in
  `run_mcp_tool` with `time.perf_counter()` and add `elapsed_ms` (int) to `_meta`.
  Namespaced as metadata, never part of the grounded answer — the research's
  recommended placement for volatile telemetry. The error envelope gets it too.
- **`build` provenance in `get_mgi_diagnostics`**: surface `build_info()`
  (`version`, `git_sha`, `built_at`) in the diagnostics payload so freshness/repro
  is observable from the operational tool, not only `get_server_capabilities`.
  `git_sha="unknown"` in a non-git source checkout is honest; in the Docker image
  the build injects `MGI_LINK_GIT_SHA` (already wired in `buildinfo.py`).

---

## 10. File-by-file change map

| File | Change |
|------|--------|
| `services/pagination.py` *(new, ~25 lines)* | `page_fields(total, returned, limit)`; pure. |
| `data/repository.py` | `phenotype_terms(marker_id, system_id, limit)` (distinct terms + `genotype_count`, support-ordered); `count_markers_by_phenotype(...)`; `count_search(...)`; `count_mp(...)`; exact-match union in `search(...)` + `match` field. Watch 500-line budget — extract ontology methods to a partial module if needed. |
| `services/shaping.py` | `shape_phenotype_terms(rows, mode)` and `shape_phenotype_genotypes(rows, mode)`; keep existing shapers. |
| `services/mgi_service.py` | `get_phenotypes` dispatches term-view vs genotype-view by mode, wires `page_fields`; `search` wires exact-boost + page; `get_alleles`/`find_markers_by_phenotype`/`search_phenotype_terms` wire page; `get_marker` summary key rename; `phenotype_summary` consumer rename. |
| `mcp/envelope.py` | `elapsed_ms` timing in `run_mcp_tool`; add to success + error `_meta`. |
| `mcp/next_commands.py` | `widen_cmd(...)`; `after_phenotypes`/`after_alleles`/`after_find_by_pheno`/`after_search`/`after_search_terms` inject widen step when truncated. |
| `mcp/schemas.py` | add `total/returned/limit/truncated` to the five list schemas; `match` on search items; `genotype_count`/`systems` on phenotype items; `build` on diagnostics. |
| `mcp/tools/phenotypes.py`, `markers.py`, `alleles.py`, `ontology.py`, `discovery.py` | update tool descriptions (term-vs-genotype modes, exact-match note, truncation contract, include_descendants); pass widen-aware next_commands; diagnostics build block. |
| `mcp/capabilities.py` | `response_mode_semantics`, `behavioral_defaults`, `truncation_contract`, `field_glossary` (allele denominators); bump nothing structural. |
| `mcp/resources.py`, `constants.py` | reference-note text for the truncation contract + glossary; server-instructions tweak. |
| `mgi_link/__init__.py` | `__version__` 0.1.0 → **0.2.0** (behavioural change). |
| `tests/fixtures/*` | add a shared-synonym ambiguity pair (MRK_List2 + lookup) for F7. |
| `tests/unit/*` | TDD: new tests for truncation contract, term-view ordering/dedup, exact-match boost, ambiguity fixture, allele-label rename, elapsed_ms, diagnostics build. Update tests asserting old field names. |
| `MCP_EVALUATION.md` | append a "Remediation" addendum mapping each finding to its fix + the new contract. |

---

## 11. Testing strategy (TDD, real fixture index)

Follow the existing pattern: build a real SQLite index from trimmed fixture
reports; exercise tools through the live FastMCP facade (no DB mocking). Per
finding, write the failing test first, then implement:

- **F1**: every list tool returns `total/returned/limit/truncated`; `truncated`
  true when capped; widen `next_command` present and points to a higher limit.
- **F2/F4**: term-view is deduplicated and support-ordered; a high-`genotype_count`
  term precedes a low one; default `compact` for the Pkd1-analog fixture contains
  the salient renal term; `minimal` has no duplicate `(mp_id)`.
- **F3**: `search_markers` for an exact fixture symbol pins it at rank 1 with
  `match="exact_symbol"`, even when a substring-matching decoy has higher FTS rank.
- **F5**: `compact` vs `full` phenotype payloads differ in shape (term vs genotype).
- **F6**: `get_marker.summary.alleles_total` and
  `get_marker_phenotypes.summary.phenotyped_alleles` exist; old `alleles` key gone.
- **F7**: ambiguity fixture triggers `ambiguous_query` with candidates +
  per-candidate `next_commands`.
- **F10**: `_meta.elapsed_ms` is an int ≥ 0 on success and error; diagnostics
  carries a `build` block.

**Definition of done:** `make ci-local` green (format, lint, 500-line budget, mypy
strict, tests) **and** a live re-probe of F1/F2/F3 against `data/mgi.sqlite`
confirming: Pkd1 default lists polycystic kidney + a truncation contract;
`search_markers("Pax6")` returns the gene at rank 1; `find_markers_by_phenotype`
exposes a real `total`.

---

## 12. Out of scope (YAGNI)

Opaque cursor pagination (the flat total/limit contract is sufficient for an
offline index and far easier for an LLM to use); multigenic genotypes, IMSR, GXD
(already declared v2); changing the resolver's human-collision code path (the
resolved marker is already correct — documentation suffices).
