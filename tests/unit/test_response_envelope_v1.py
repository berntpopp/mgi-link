"""Locking regression test for the GeneFoundry Response-Envelope Standard v1.

Encodes the ratified fleet-wide contract at mgi-link's MCP wrapper boundary
(``mgi_link/mcp/envelope.py``):

- SUCCESS: ``{"success": True, <payload>, "_meta": {...}}``.
- FAILURE: a FLAT in-band dict -- ``{"success": False, "error_code": str,
  "message": str, "retryable": bool, "recovery_action": str, "_meta": {...}}``
  -- never a bare exception, never a nested ``error: {}`` object.

mgi-link has two real error-producing mechanisms, both in ``envelope.py``:

- :func:`run_mcp_tool` classifies any exception raised inside a tool body
  (via its internal ``_error_envelope`` helper) into the flat shape above.
- :func:`build_arg_error_envelope` is called by
  ``mgi_link.mcp.middleware.ArgValidationMiddleware`` for pydantic
  argument-binding failures caught *before* a tool body runs (so they never
  reach ``run_mcp_tool``'s try/except).

DOCUMENTED DRIFT from the fleet-ideal contract: the ratified standard asks
for ``_meta.unsafe_for_clinical_use: True`` on every call. mgi-link ships
without it -- deliberately. ``mgi_link/mcp/capabilities.py``'s
``build_capabilities()`` explicitly enumerates ``per_call_meta`` as
``["tool", "request_id", "next_commands"]`` and documents that static
provenance (including the research-use restriction) is declared ONCE in
``get_server_capabilities`` rather than repeated per-call, to conserve
tokens. This test locks the REAL shape mgi-link ships, not the ideal one --
see the final agent report for this drift called out explicitly.
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
    # Documented drift: no per-call clinical-use banner (see module docstring).
    assert "unsafe_for_clinical_use" not in meta


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
    # Documented drift: no per-call clinical-use banner (see module docstring).
    assert "unsafe_for_clinical_use" not in meta


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
    # Documented drift: no per-call clinical-use banner (see module docstring).
    assert "unsafe_for_clinical_use" not in env["_meta"]
