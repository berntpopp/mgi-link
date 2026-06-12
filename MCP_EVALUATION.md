# mgi-link MCP — Evaluation & Improvement Plan

**Date:** 2026-06-12
**Evaluator:** LLM consumer + senior MCP-tester perspective (live black-box testing)
**Method:** ~37 live tool calls against the running server — happy paths, all four
response modes, the argument-alias mechanism, limit clamping, ontology-descendant
rollup, and every deliberately-triggerable error code.

### Environment under test

| Property | Value |
|---|---|
| Server version | `0.1.0` (build `git_sha: unknown`) |
| MGI release loaded | Mon, 08 Jun 2026 |
| Markers / Alleles / GenoPheno | 656,695 / 129,258 / 282,311 |
| MP terms / Orthologs / Diseases | 15,205 / 21,930 / 4,418 |
| Tools | 13 |
| Response modes | `minimal`, `compact`, `standard`, `full` (default `compact`) |
| Error taxonomy | `invalid_input`, `not_found`, `ambiguous_query`, `data_unavailable`, `rate_limited`, `upstream_unavailable`, `internal_error` |

---

## 1. Executive summary

**Overall grade: B+ (7.5 / 10).**

The server's *contract layer* is excellent — a uniform response envelope, a
best-in-class error taxonomy with recovery hints, transparent argument aliasing,
and a two-tier discovery surface (`get_server_capabilities` + `mgi://` resources).
A cold LLM can self-orient in one call and recover from errors unaided.

The weaknesses are **concentrated and fixable**, and they live in the two
highest-traffic tools (`get_marker_phenotypes`, `find_markers_by_phenotype`) plus
`search_markers` relevance. None are crashes. The dangerous ones are **silent
truncation** failures: results that look complete but are not. For a server whose
entire purpose is *faithful grounding*, that is the worst failure mode, because it
causes a confident, wrong answer rather than a visible error.

> **The single most important fix:** `get_marker_phenotypes` truncates its result
> set *alphabetically* with no truncation flag. For `PKD1` this silently drops
> `kidney cyst` and `polycystic kidney` — the defining phenotypes of the gene.
> A naive caller would summarize PKD1 and never mention polycystic kidney.

### Grades at a glance

| Dimension (LLM-UX) | Score | Per-tool (tester) | Grade |
|---|---|---|---|
| Discoverability | 9 | get_server_capabilities | A |
| Error handling | 9 | get_mgi_diagnostics | A |
| Response envelope / consistency | 9 | get_phenotype_overview | A |
| Speed | 8 | get_mp_term / get_marker_ortholog | A |
| Chaining (`next_commands`) | 7 | resolve_marker / get_marker | A− |
| Observability | 6 | get_marker_alleles / get_marker_diseases | A− |
| **Token efficiency** | **4** | search_phenotype_terms | A− |
| | | **find_markers_by_phenotype** | **C+** |
| | | **search_markers** | **C+** |
| | | **get_marker_phenotypes** | **C** |

---

## 2. What works well (keep / protect)

- **Discovery (9/10).** `get_server_capabilities` is exemplary at both `detail`
  levels: tool signatures, response modes, recommended workflows, error codes,
  limits, match-type/allele-type/marker-type vocabularies, scope notes, the
  not-found contract, and id-normalization rules. Backed by `mgi://capabilities`
  and `mgi://tools` resources.
- **Error handling (9/10).** Every error is machine-actionable. Example
  (`resolve_marker` on a bogus symbol):
  ```json
  {"error_code":"not_found","retryable":false,
   "recovery_action":"reformulate_input",
   "_meta":{"next_commands":[{"tool":"search_markers","arguments":{"query":"..."}}]}}
  ```
  Validation is graceful and specific: limit overflow returns `invalid_input`
  with `field` and an allowed range; malformed `mp_id` is rejected *before*
  lookup; unknown arguments return `allowed_values`.
- **Envelope consistency (9/10).** Every payload carries `success`, `_meta.tool`,
  `_meta.request_id`, and `_meta.next_commands` (on success *and* error).
- **Argument aliasing.** `gene_symbol`, `symbol`, `hgnc`, etc. all resolve to
  `query`, and an applied rewrite is disclosed under
  `_meta.argument_aliases_applied` — transparent and verified working.
- **`get_phenotype_overview` is the reference design.** Deduplicated,
  system-grouped, and complete. It is the shape the other phenotype tools should
  imitate.
- **Cross-species ergonomics.** Passing a human symbol (`NAA10`, `PKD1`) and
  getting the mouse ortholog "just works" — no manual ID wrangling.

---

## 3. Findings by severity

### HIGH — correctness / grounding safety

**F1 — Silent truncation with no total/returned contract.**
`find_markers_by_phenotype(MP:0008528, limit=10)` returns `count: 10`, but
`count` equals the limit and there is **no field for the true total**. A caller
asking "how many genes cause polycystic kidney" reads `count:10` and concludes
exactly ten. `get_marker_phenotypes` is the same class: a default call returns
`returned:100` against `summary.phenotypes:126` with **no `truncated` flag**.

**F2 — `get_marker_phenotypes` truncates *alphabetically*.**
The 100-row cap cuts at "enlarged kidney", silently dropping `kidney cyst` and
`polycystic kidney` for PKD1. Ordering by alphabet hides whatever sorts late,
regardless of clinical importance. `_meta.next_commands` on the truncated
response does **not** point at a recovery path (it suggests
`get_phenotype_overview`/`get_marker_diseases`, neither of which returns the
dropped annotations).

**F3 — `search_markers` does not surface the gene you searched for.**
`search_markers("Pax6")` returns 25 hits and the canonical **Pax6 gene
(MGI:97490) is not among them** — it is outscored by transgenes, deletions, and
two antisense lncRNAs (`Paupar` 10.7, `Pax6os1` 8.75) that merely contain "Pax6"
in their names. Even filtered to `marker_type=Gene`, the gene ranks **last**
(score 6.4) behind the two lncRNAs. Exact symbol/synonym matches must be pinned to
the top.

### MEDIUM — efficiency / usability

**F4 — `minimal` mode emits duplicate rows.**
`get_marker_phenotypes(PKD1, response_mode=minimal)` strips to
`{mp_id, mp_term}` but keeps row-level duplication — `edema` ×9, `enlarged
kidney` ×7, all byte-identical. It wastes the exact tokens `minimal` exists to
save, and the dupes consume the truncation budget, so the caller sees *fewer*
distinct phenotypes than necessary.

**F5 — `response_mode` is largely inert.**
For `get_marker_phenotypes`, `compact == standard == full` (all return the rich
per-genotype object); only `minimal` differs. For `get_marker`,
`standard == full` are byte-identical (`compact` does trim
`cm_position`/`status`/`refseq_id`). Four modes are advertised; ~2 distinct
outputs actually exist.

**F6 — "alleles" means different populations in different tools.**
`get_marker(Wt1).summary.alleles = 31` (all alleles),
`get_marker_phenotypes(Wt1).summary.alleles = 12` (phenotyped alleles),
`get_marker_alleles(Pkd1).total_alleles = 46`. Same label, three populations, no
qualifier — an easy source of arithmetic errors in a downstream summary.

### LOW — consistency / observability / polish

**F7 — `ambiguous_query` never fired.** The documented `not_found_contract`
promises a candidate list for ambiguous symbols, but every probe — one-to-many
orthologs (`IFNA1`→single `Ifna1`), MHC complex (`H2-D`), shared synonyms
(`agouti`→`a`), gene complexes (`Hbb`, `Tcrb`) — resolved to a single best match.
Either the resolver always picks a winner (making the candidate-list contract dead
code) or its trigger is very narrow and unverified.

**F8 — `match_type` for human input is coincidence-dependent.** `NAA10`→
`ortholog`, but `BRCA2`→`current` (matched mouse `Brca2` by case-insensitive
symbol collision). The two human genes take different code paths based purely on
whether the mouse symbol happens to match.

**F9 — `include_descendants` defaults to `true`.** Confirmed: `kidney cyst` with
the flag off → 5 exact-annotation genes; on → a different, expanded set. A
reasonable default, but it changes *which* genes are returned and is not flagged
in the tool signature.

**F10 — No latency telemetry; `git_sha` unpopulated.** No `elapsed_ms` anywhere
in `_meta` (speed is good but unobservable to the client). `build.git_sha` is
`"unknown"` — the field is plumbed but not filled, half-wiring reproducibility
tracing.

---

## 4. Recommendations (prioritized & actionable)

### P0 — grounding safety (do first)

1. **Add a truncation contract to every list tool.** Return
   `{ total, returned, truncated, limit }` on `get_marker_phenotypes`,
   `find_markers_by_phenotype`, `get_marker_alleles`, `search_markers`, and
   `search_phenotype_terms`. When `truncated` is true, inject a `next_commands`
   entry that widens the query (raise `limit` or paginate).
   *Most urgent:* `find_markers_by_phenotype` exposes no total at all.

2. **Re-shape `get_marker_phenotypes` ordering.** Stop alphabetical ordering that
   buries salient terms. Either:
   - order by salience (system-grouped, or by genotype-support count), **or**
   - default to a deduplicated term-level view (reuse the
     `get_phenotype_overview` shaping that already works well) and make the
     per-genotype rows opt-in via `response_mode=full`.

### P1 — efficiency & discoverability

3. **Fix `minimal` mode** to deduplicate to distinct `(mp_id, mp_term)` pairs,
   each with a `genotype_count`. This makes `minimal` both correct and the
   5–8× token win it is meant to be.

4. **Differentiate or trim `response_mode`.** Either make `compact` / `standard`
   / `full` genuinely tiered (currently identical for `get_marker_phenotypes`),
   or reduce the advertised list to the modes that differ and document the
   per-mode field deltas.

5. **Boost exact matches in `search_markers`.** Pin an exact symbol or synonym
   hit to rank 1 (or add an `exact_match` field). Searching `Pax6` must surface
   the Pax6 gene, not bury it below transgenes.

### P2 — consistency, observability, polish

6. **Add `_meta.elapsed_ms`** to every response; **populate `build.git_sha`**.

7. **Disambiguate allele counts** across tools — e.g. `alleles_total` vs
   `alleles_phenotyped` — so the same label never means three different things.

8. **Resolve the `ambiguous_query` contract.** Add a regression fixture that
   actually triggers it; if the resolver always picks a single best match, either
   implement true ambiguity detection or remove the documented candidate-list
   contract.

9. **Document behavioral defaults.** Surface `include_descendants=true` in the
   tool signature/description, and document that a human symbol may resolve as
   `current` (case collision) rather than `ortholog`.

---

## 5. Test coverage (for reproducibility)

All 13 tools exercised. ~37 calls across two parallel waves plus targeted probes.

| Tool | Cases run |
|---|---|
| get_server_capabilities | `detail=summary`, `detail=full` |
| get_mgi_diagnostics | default |
| resolve_marker | mouse symbol, bare MGI id (`98968`), human ortholog (`NAA10`), synonym (`agouti`→`a`), complex (`Hbb`, `Tcrb`, `H2-D`), 1-to-many ortholog (`IFNA1`), human=mouse symbol (`BRCA2`), not_found, free-text not_found (`kidney`) |
| get_marker | `standard`, `full`, `compact` (via alias), not_found, unknown-arg `invalid_input` |
| search_markers | default, `marker_type=Gene` filter, zero-result |
| get_marker_alleles | default (limit 5), `allele_type=Targeted`, limit overflow (`invalid_input`) |
| get_marker_phenotypes | default `compact`, `minimal`, `standard`, `full`, `mp_system` filter, observed truncation |
| get_phenotype_overview | full grid (22 systems) |
| get_marker_diseases | `Pkd1` (3 diseases) |
| get_marker_ortholog | `full` |
| get_mp_term | valid, not_found (`MP:9999999`), malformed (`banana`) |
| search_phenotype_terms | `polycystic kidney` (25 hits) |
| find_markers_by_phenotype | default, `include_descendants` true/false, malformed `mp_id` |

**Error codes triggered:** `invalid_input` ✓ (limit overflow, malformed mp_id,
unknown arg), `not_found` ✓ (resolve / get_marker / get_mp_term).
**Not triggered:** `ambiguous_query` (see F7), and the operational codes
`data_unavailable` / `rate_limited` / `upstream_unavailable` / `internal_error`
(not deliberately inducible in a black-box test).

---

## 6. Remediation (v0.2.0 — implemented 2026-06-12)

All ten findings were closed. Design spec:
`docs/superpowers/specs/2026-06-12-mgi-link-evaluation-remediation-design.md`;
implementation plan:
`docs/superpowers/plans/2026-06-12-mgi-link-evaluation-remediation.md`.

| ID | Fix shipped |
|----|-------------|
| **F1** | Uniform truncation contract `{total, returned, limit, truncated}` on every list tool (`search_markers`, `get_marker_alleles`, `get_marker_phenotypes`, `find_markers_by_phenotype`, `search_phenotype_terms`). `truncated` is computed server-side; when true, `_meta.next_commands` carries a ready-to-call **widen** step. `find_markers_by_phenotype` now exposes a real `total` (distinct annotated markers, descendants-aware). |
| **F2** | `get_marker_phenotypes` no longer truncates alphabetically. The default view is a **deduplicated DISTINCT-term list ordered by genotype support** (`genotype_count` desc), default `limit` raised 100→250 so a typical gene returns all distinct terms. Pkd1's `polycystic kidney` and `kidney cyst` are now present in the default response; any cap is explicit and drops only low-support tail terms. |
| **F3** | `search_markers` pins **exact symbol/synonym matches first** (each hit carries `match: exact_symbol\|exact_synonym\|fts`) regardless of bm25 score. `Pax6` now returns the Pax6 gene (MGI:97490) at rank 1 instead of being buried below deletions/lncRNAs/transgenes. |
| **F4** | `minimal` mode is deduplicated by construction (one row per distinct `(mp_id, mp_term)` with `genotype_count`); no more `edema ×9`. |
| **F5** | `response_mode` is genuinely tiered for phenotypes (compact/standard = term view, `full` = per-genotype rows) and the per-mode field deltas are documented in `capabilities.response_mode_semantics`. The returned `view` field states which shape was emitted. |
| **F6** | Allele-count labels are now explicit and unambiguous: `alleles_total` (get_marker), `total_alleles` (get_marker_alleles) = all alleles; `phenotyped_alleles` (phenotype summary) = the annotated subset. Documented in `capabilities.field_glossary`. |
| **F7** | The `ambiguous_query` contract is proven by a deterministic fixture (two markers sharing a synonym) plus service + e2e regression tests asserting the candidate list and per-candidate `next_commands`. |
| **F8** | Documented that a human symbol identical to the mouse symbol resolves as `match_type=current` (case collision) rather than `ortholog` — in the `resolve_marker` description and `capabilities.behavioral_defaults`. |
| **F9** | `include_descendants=true` default is surfaced in the tool description and `capabilities.behavioral_defaults`, and the flag is echoed in every response. |
| **F10** | `_meta.elapsed_ms` is added to every success and error response (namespaced as telemetry, per best practice); `get_mgi_diagnostics` now reports the `build` block (`version`, `git_sha`, `built_at`). |

**Verification:** `make ci-local` green (format, lint, 500-line budget, mypy strict,
tests) and a live re-probe against the loaded index confirms the three grounding
fixes — Pkd1's defining renal phenotypes present by default with a truncation
contract, `Pax6` gene at search rank 1, and a real `total` on the reverse lookup.
Server version bumped to `0.2.0`.

---

*Research-use-only data source. This document evaluates the MCP server interface,
not the underlying MGI data, which is curated by The Jackson Laboratory.*
