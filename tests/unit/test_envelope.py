"""Unit tests for the MCP envelope boundary and error classification."""

from __future__ import annotations

from typing import Any

import pytest

from mgi_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    DownloadError,
    InvalidInputError,
    NotFoundError,
    RateLimitError,
    WithdrawnEntryError,
)
from mgi_link.mcp.envelope import (
    McpErrorContext,
    McpToolError,
    build_arg_error_envelope,
    run_mcp_tool,
)
from mgi_link.mcp.untrusted_content import UntrustedTextLimitError


async def test_success_injects_meta() -> None:
    async def call() -> dict[str, Any]:
        return {"mgi_id": "MGI:1"}

    out = await run_mcp_tool("get_marker", call, context=McpErrorContext("get_marker"))
    assert out["success"] is True
    assert out["_meta"]["tool"] == "get_marker"
    assert "request_id" in out["_meta"]


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (NotFoundError("nope"), "not_found"),
        (InvalidInputError("bad", field="query"), "invalid_input"),
        (DataUnavailableError(), "data_unavailable"),
        (RateLimitError(), "rate_limited"),
        (DownloadError("net"), "upstream_unavailable"),
        (McpToolError(error_code="internal_error", message="x"), "internal_error"),
        (UntrustedTextLimitError("too many objects"), "response_limit_exceeded"),
    ],
)
async def test_error_classification(exc: Exception, code: str) -> None:
    async def call() -> dict[str, Any]:
        raise exc

    out = await run_mcp_tool("resolve_marker", call, context=McpErrorContext("resolve_marker"))
    assert out["success"] is False
    assert out["error_code"] == code
    assert out["_meta"]["next_commands"]  # always present


async def test_untrusted_text_limit_error_is_typed_not_internal() -> None:
    """A v1.1 limit breach must surface as its own typed code, never internal_error."""

    async def call() -> dict[str, Any]:
        raise UntrustedTextLimitError("untrusted object count 300 exceeds ceiling 200")

    out = await run_mcp_tool(
        "search_phenotype_terms", call, context=McpErrorContext("search_phenotype_terms")
    )
    assert out["success"] is False
    assert out["error_code"] == "response_limit_exceeded"
    assert out["error_code"] != "internal_error"
    assert out["retryable"] is False
    assert out["recovery_action"] == "reformulate_input"


async def test_invalid_input_surfaces_field_and_allowed() -> None:
    async def call() -> dict[str, Any]:
        raise InvalidInputError("bad", field="mp_system", allowed=["a", "b"], hint="use a system")

    out = await run_mcp_tool("get_marker_phenotypes", call)
    assert out["field"] == "mp_system"
    assert out["allowed_values"] == ["a", "b"]
    assert out["hint"] == "use a system"


async def test_ambiguous_candidates_chain() -> None:
    async def call() -> dict[str, Any]:
        raise AmbiguousQueryError("ambig", candidates=[{"mgi_id": "MGI:1"}, {"mgi_id": "MGI:2"}])

    out = await run_mcp_tool("resolve_marker", call)
    assert out["error_code"] == "ambiguous_query"
    assert out["candidates"][0]["mgi_id"] == "MGI:1"
    assert out["_meta"]["next_commands"][0]["arguments"]["query"] == "MGI:1"


async def test_withdrawn_entry_envelope() -> None:
    async def call() -> dict[str, Any]:
        raise WithdrawnEntryError("MGI:9", status="withdrawn", replaced_by=[{"mgi_id": "MGI:10"}])

    out = await run_mcp_tool("get_marker", call)
    assert out["error_code"] == "not_found"
    assert out["obsolete"] is True
    assert out["_meta"]["next_commands"][0]["arguments"]["query"] == "MGI:10"


def test_build_arg_error_envelope_unknown_arg() -> None:
    env = build_arg_error_envelope(
        tool_name="get_marker",
        loc="queryy",
        error_type="unexpected_keyword_argument",
        valid_params=["query", "response_mode"],
        signature="get_marker(query, response_mode=)",
        suggestion="query",
    )
    assert env["error_code"] == "invalid_input"
    assert "query" in env["allowed_values"]
    assert "Did you mean `query`" in env["message"]


def test_build_arg_error_envelope_bad_value() -> None:
    env = build_arg_error_envelope(
        tool_name="search_markers",
        loc="limit",
        error_type="invalid",
        valid_params=["query", "limit"],
        signature="search_markers(query, limit=)",
        suggestion=None,
        constraints=(["1..200"], "must be between 1 and 200"),
    )
    assert env["allowed_values"] == ["1..200"]
    assert "must be between" in env["message"]
