"""Regression tests for the MCP Contract-Hardening v1 sweep (issue #28).

Written BEFORE the fix and watched to fail (TDD). They lock the two confirmed
HIGH defects and the fleet-wide four:

D1  Conditional/Cre-driven genotypes are excluded by MGI_GenePheno, so a
    well-studied gene (HNF1B) can report ZERO renal phenotypes with success:true.
    The empty result must be self-describing: every phenotype response carries an
    explicit scope flag so a zero count is never mistaken for "no such phenotype".
D2  An invalid ``mp_system`` returned only the two whitespace-free system names
    (``mortality/aging``/``neoplasm``); the envelope sanitiser dropped every
    multi-word (server-controlled, trusted) vocabulary value. allowed_values must
    list the FULL valid set.

Fleet-four: isError:true on every error envelope; error_code closed to the six-
value enum; unrecognised closed-vocabulary filter values rejected (never silently
matched to nothing).
"""

from __future__ import annotations

from typing import Any

import pytest

from mgi_link.services.mgi_service import MgiService

pytestmark = pytest.mark.mcp

_CANON_CODES = {
    "invalid_input",
    "not_found",
    "ambiguous_query",
    "upstream_unavailable",
    "rate_limited",
    "internal",
}

_SCOPE = "single_locus_genotypes_only"


# --------------------------------------------------------------------------- D1


async def test_phenotypes_carry_explicit_scope_flag(facade: Any, structured: Any) -> None:
    """get_marker_phenotypes declares its single-locus scope in the RESPONSE."""
    env = structured(await facade.call_tool("get_marker_phenotypes", {"query": "Wt1"}))
    assert env["success"] is True
    assert env["scope"] == _SCOPE
    assert env["excludes_conditional_genotypes"] is True
    assert "conditional" in env["scope_note"].lower()


async def test_overview_carries_explicit_scope_flag(facade: Any, structured: Any) -> None:
    """get_phenotype_overview declares the same scope (no false gene-page parity)."""
    env = structured(await facade.call_tool("get_phenotype_overview", {"query": "Wt1"}))
    assert env["scope"] == _SCOPE
    assert "conditional" in env["scope_note"].lower()


def test_zero_result_phenotype_query_is_still_scoped(service: MgiService) -> None:
    """A confidently-empty renal-style result is the dangerous class (the HNF1B
    repro): it MUST carry the scope flag so a zero count is distinguishable from
    'this gene has no such phenotype'. Pax6 has a cardiovascular annotation but no
    renal one, mirroring HNF1B's empty renal result on the live server."""
    out = service.get_phenotypes("Pax6", mp_system="renal/urinary system")
    assert out["total"] == 0
    assert out["annotations"] == []
    assert out["scope"] == _SCOPE
    assert out["excludes_conditional_genotypes"] is True
    assert "conditional" in out["scope_note"].lower()


async def test_overview_description_drops_gene_page_parity_claim(facade: Any) -> None:
    """The get_phenotype_overview description must not claim to mirror the MGI gene
    page (which includes the excluded conditional/multi-genic genotypes)."""
    tools = {t.name: t for t in await facade.list_tools()}
    desc = tools["get_phenotype_overview"].description or ""
    assert "conditional" in desc.lower()


# --------------------------------------------------------------------------- D2


async def test_invalid_mp_system_lists_full_vocabulary(
    facade: Any, structured: Any, repo: Any
) -> None:
    """The invalid mp_system error must list the FULL top-level MP system set (every
    server-controlled system in the grid), including multi-word names — not just the
    2 whitespace-free survivors of the envelope sanitiser, and not a mere subset."""
    from mgi_link.constants import MP_TOP_SYSTEM_NAMES

    env = structured(
        await facade.call_tool(
            "get_marker_phenotypes", {"query": "Wt1", "mp_system": "kidney stuff"}
        )
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "mp_system"
    allowed = env["allowed_values"]
    # The full set the server can validate: every grid system that is a member of the
    # curated server-controlled allowlist (ontology-only labels are excluded).
    expected = {s["name"] for s in repo.top_systems() if s["name"] in MP_TOP_SYSTEM_NAMES}
    assert expected  # sanity: the fixture has real MP systems
    assert set(allowed) == expected
    assert "renal/urinary system phenotype" in allowed


def test_mp_system_error_never_leaks_ontology_only_labels(service: MgiService, repo: Any) -> None:
    """allowed_values is built from the SERVER allowlist, so an ontology-derived label
    that is NOT a curated system (the fixture's synthetic 'tumorigenesis') is dropped —
    an OBO-injected label can never reach the caller (issue #28 review, D2)."""
    from mgi_link.constants import MP_TOP_SYSTEM_NAMES
    from mgi_link.exceptions import InvalidInputError

    grid = {s["name"] for s in repo.top_systems()}
    ontology_only = grid - MP_TOP_SYSTEM_NAMES
    assert ontology_only  # the fixture has at least one synthetic system
    with pytest.raises(InvalidInputError) as exc:
        service.get_phenotypes("Wt1", mp_system="not a real system")
    assert set(exc.value.allowed or []).isdisjoint(ontology_only)


def test_find_markers_by_phenotype_carries_scope(service: MgiService) -> None:
    """The reverse lookup reads the SAME single-locus population: an MP term with no
    single-locus markers must not look authoritatively empty (issue #28, D1 class)."""
    out = service.find_markers_by_phenotype("MP:0005367")
    assert out["scope"] == _SCOPE
    assert out["excludes_conditional_genotypes"] is True


def test_get_marker_summary_phenotype_counts_are_scoped(service: MgiService) -> None:
    """get_marker's phenotype summary counts are single-locus-scoped and say so."""
    marker = service.get_marker("Wt1")
    assert marker["summary"]["phenotype_scope"] == _SCOPE


async def test_bogus_marker_type_rejected_not_silently_empty(facade: Any, structured: Any) -> None:
    env = structured(
        await facade.call_tool("search_markers", {"query": "Pax6", "marker_type": "__nope__"})
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "marker_type"
    assert "Gene" in env["allowed_values"]


async def test_bogus_allele_type_rejected_not_silently_empty(facade: Any, structured: Any) -> None:
    env = structured(
        await facade.call_tool("get_marker_alleles", {"query": "Wt1", "allele_type": "__nope__"})
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "allele_type"
    assert "Targeted" in env["allowed_values"]


async def test_marker_and_allele_type_declare_schema_enum(facade: Any) -> None:
    """The closed vocabulary is declared as a schema enum, so a schema-validating
    client rejects `__nope__` BEFORE the call — not only the runtime (review point 2)."""
    tools = {t.name: t for t in await facade.list_tools()}
    mt = (tools["search_markers"].parameters or {})["properties"]["marker_type"]
    assert "Gene" in mt.get("enum", []) and "__nope__" not in mt.get("enum", [])
    at = (tools["get_marker_alleles"].parameters or {})["properties"]["allele_type"]
    assert {"Targeted", "knockout", "crispr"} <= set(at.get("enum", []))


async def test_known_marker_type_still_works_case_insensitively(
    facade: Any, structured: Any
) -> None:
    """The rejection must not break a legitimate (even lower-cased) filter."""
    env = structured(
        await facade.call_tool("search_markers", {"query": "Pax6", "marker_type": "gene"})
    )
    assert env["success"] is True


# ------------------------------------------------------------------ fleet-four


async def test_error_envelopes_set_mcp_is_error(facade: Any) -> None:
    """Every error envelope must carry MCP isError:true (both error paths)."""
    # tool-body error path (run_mcp_tool)
    not_found = await facade.call_tool("resolve_marker", {"query": "Zzzznotreal"})
    assert not_found.is_error is True
    # arg-binding error path (ArgValidationMiddleware)
    bad_arg = await facade.call_tool("get_marker", {"totally_unknown_arg": "x"})
    assert bad_arg.is_error is True
    # a success must NOT be flagged
    ok = await facade.call_tool("resolve_marker", {"query": "Wt1"})
    assert not ok.is_error


async def test_all_error_codes_are_in_the_closed_enum(facade: Any, structured: Any) -> None:
    """No tool may emit an error_code outside the six-value fleet enum."""
    probes = [
        ("resolve_marker", {"query": "Zzzznotreal"}),  # not_found
        ("resolve_marker", {"query": "Dup1"}),  # ambiguous_query
        ("get_mp_term", {"mp_id": "not-an-mp-id"}),  # invalid_input
        ("get_marker", {"totally_unknown_arg": "x"}),  # invalid_input (arg-bind)
        ("get_marker_phenotypes", {"query": "Wt1", "mp_system": "kidney stuff"}),  # invalid_input
    ]
    for tool, args in probes:
        env = structured(await facade.call_tool(tool, args))
        assert env["success"] is False
        assert env["error_code"] in _CANON_CODES, (tool, env["error_code"])


async def test_cold_start_maps_to_upstream_unavailable(cold_facade: Any, structured: Any) -> None:
    """The legacy 'data_unavailable' code is closed onto the canonical enum."""
    env = structured(await cold_facade.call_tool("resolve_marker", {"query": "Wt1"}))
    assert env["success"] is False
    assert env["error_code"] == "upstream_unavailable"
