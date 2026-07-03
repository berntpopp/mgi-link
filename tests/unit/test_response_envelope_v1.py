"""Locking regression test for the GeneFoundry Response-Envelope Standard v1.

Encodes the ratified fleet-wide contract at mgi-link's MCP wrapper boundary
(``mgi_link/mcp/envelope.py``):

- SUCCESS: ``{"success": True, <payload>, "_meta": {...}}``.
- FAILURE: a FLAT in-band dict -- ``{"success": False, "error_code": str,
  "message": str, "retryable": bool, "recovery_action": str, "_meta": {...}}``
  -- never a bare exception, never a nested ``error: {}`` object.
- ``_meta.unsafe_for_clinical_use`` is ``True`` on EVERY tool response --
  success and error alike, at every ``response_mode`` (minimal/compact/
  standard/full). This is the fleet's per-call research-use disclaimer
  (2026-07-03 standardization); it is layered on top of, not a replacement
  for, the static provenance text declared once in
  ``get_server_capabilities``.

mgi-link has two real error-producing mechanisms, both in ``envelope.py``:

- :func:`run_mcp_tool` classifies any exception raised inside a tool body
  (via its internal ``_error_envelope`` helper) into the flat shape above.
- :func:`build_arg_error_envelope` is called by
  ``mgi_link.mcp.middleware.ArgValidationMiddleware`` for pydantic
  argument-binding failures caught *before* a tool body runs (so they never
  reach ``run_mcp_tool``'s try/except).

Formerly this repo shipped a DOCUMENTED DRIFT from the fleet-ideal contract
(no per-call ``unsafe_for_clinical_use``); that drift is now closed -- see
``envelope.py``'s module-level ``_UNSAFE_FOR_CLINICAL_USE_META`` constant,
which is merged in last on every envelope-building path.
"""

from __future__ import annotations

from typing import Any

from mgi_link.exceptions import NotFoundError
from mgi_link.mcp.envelope import McpErrorContext, build_arg_error_envelope, run_mcp_tool


async def test_success_envelope_matches_response_envelope_standard_v1() -> None:
    """run_mcp_tool's success path injects the flat success banner + dynamic _meta."""

    async def call() -> dict[str, Any]:
        return {"results": [{"mgi_id": "MGI:97490", "symbol": "Pax6"}]}

    out = await run_mcp_tool(
        "get_marker_phenotypes",
        call,
        context=McpErrorContext("get_marker_phenotypes"),
    )

    assert out["success"] is True
    assert out["results"] == [{"mgi_id": "MGI:97490", "symbol": "Pax6"}]

    meta = out["_meta"]
    assert meta["tool"] == "get_marker_phenotypes"
    assert isinstance(meta["request_id"], str) and meta["request_id"]
    assert isinstance(meta["elapsed_ms"], int)
    # Per-call research-use disclaimer: mandatory on every success response.
    assert meta["unsafe_for_clinical_use"] is True


async def test_error_envelope_is_flat_and_matches_response_envelope_standard_v1() -> None:
    """run_mcp_tool's exception path is a FLAT success:false dict, never nested/bare."""

    async def call() -> dict[str, Any]:
        raise NotFoundError("MGI:999999999 not found.")

    out = await run_mcp_tool(
        "get_marker_phenotypes",
        call,
        context=McpErrorContext("get_marker_phenotypes", arguments={"query": "MGI:999999999"}),
    )

    assert out["success"] is False
    assert isinstance(out["error_code"], str) and out["error_code"]
    assert isinstance(out["message"], str) and out["message"]
    assert isinstance(out["retryable"], bool)
    assert isinstance(out["recovery_action"], str) and out["recovery_action"]
    assert "error" not in out  # flat -- no nested error object

    meta = out["_meta"]
    assert meta["tool"] == "get_marker_phenotypes"
    # Per-call research-use disclaimer: mandatory on every error response too.
    assert meta["unsafe_for_clinical_use"] is True


def test_arg_error_envelope_is_flat_and_matches_response_envelope_standard_v1() -> None:
    """build_arg_error_envelope (the middleware's pre-dispatch path) is equally flat."""
    env = build_arg_error_envelope(
        tool_name="get_marker_phenotypes",
        loc="query",
        error_type="missing_argument",
        valid_params=["query", "mp_system", "limit", "response_mode"],
        signature="get_marker_phenotypes(query, mp_system=, limit=, response_mode=)",
        suggestion=None,
    )

    assert env["success"] is False
    assert isinstance(env["error_code"], str) and env["error_code"]
    assert isinstance(env["message"], str) and env["message"]
    assert isinstance(env["retryable"], bool)
    assert isinstance(env["recovery_action"], str) and env["recovery_action"]
    assert "error" not in env  # flat -- no nested error object

    assert env["_meta"]["tool"] == "get_marker_phenotypes"
    # Per-call research-use disclaimer: mandatory on the arg-binding error path too.
    assert env["_meta"]["unsafe_for_clinical_use"] is True


def test_arg_error_envelope_with_constraints_carries_disclaimer() -> None:
    """The constraints branch of build_arg_error_envelope also stamps the disclaimer."""
    env = build_arg_error_envelope(
        tool_name="search_markers",
        loc="limit",
        error_type="invalid",
        valid_params=["query", "limit"],
        signature="search_markers(query, limit=)",
        suggestion=None,
        constraints=(["1..200"], "must be between 1 and 200"),
    )

    assert env["success"] is False
    assert env["_meta"]["unsafe_for_clinical_use"] is True


async def test_disclaimer_survives_every_response_mode() -> None:
    """response_mode (minimal/compact/standard/full) never strips the disclaimer.

    mgi-link's response_mode only projects the tool *payload* shape (see
    ``mgi_link/services/shaping.py``); it never gates ``_meta`` fields. This
    test locks that: ``run_mcp_tool`` merges ``unsafe_for_clinical_use`` in
    unconditionally regardless of what a tool body -- including one that
    aggressively trims its own ``_meta`` for a minimal-style response --
    returns.
    """

    for mode in ("minimal", "compact", "standard", "full"):

        async def call(mode: str = mode) -> dict[str, Any]:
            # Simulate a minimal-style tool body that returns a bare _meta.
            return {"mp_id": "MP:0005367", "response_mode": mode, "_meta": {}}

        out = await run_mcp_tool(
            "get_mp_term",
            call,
            context=McpErrorContext("get_mp_term"),
        )
        assert out["_meta"]["unsafe_for_clinical_use"] is True, (
            f"disclaimer missing at response_mode={mode}"
        )
