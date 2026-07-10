"""Tests for MCP middleware compatibility boundaries."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import MiddlewareContext
from mcp.types import CallToolRequestParams

from mgi_link.mcp.middleware import ArgValidationMiddleware


@pytest.mark.parametrize("cause", [None, RuntimeError("unrelated")])
async def test_fastmcp_validation_without_pydantic_cause_propagates(
    cause: BaseException | None,
) -> None:
    error = FastMCPValidationError("framework validation failed")
    if cause is not None:
        try:
            raise error from cause
        except FastMCPValidationError as chained:
            error = chained

    context = MiddlewareContext(
        message=CallToolRequestParams(name="get_marker", arguments={}),
        method="tools/call",
    )
    middleware = ArgValidationMiddleware()
    middleware._schema = AsyncMock(return_value={"properties": {}})  # type: ignore[method-assign]

    async def call_next(_: MiddlewareContext[Any]) -> Any:
        raise error

    with pytest.raises(FastMCPValidationError, match="framework validation failed"):
        await middleware.on_call_tool(context, call_next)
