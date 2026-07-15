"""Cross-species tools: get_marker_ortholog, get_marker_diseases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mgi_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from mgi_link.mcp.envelope import McpErrorContext, run_mcp_tool
from mgi_link.mcp.next_commands import after_diseases, after_ortholog
from mgi_link.mcp.service_adapters import get_mgi_service
from mgi_link.mcp.tools._common import QueryStr, ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_ortholog_tools(mcp: FastMCP) -> None:
    """Register ortholog / disease cross-species tools."""

    @mcp.tool(
        name="get_marker_ortholog",
        title="Get Marker Ortholog",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"ortholog", "xref"},
        description=(
            "Return the mouse<->human ortholog mapping and cross-references for a "
            "marker: human symbol, HGNC id, NCBI Gene (human), Ensembl (human), OMIM "
            "gene id, and human GRCh38 coordinates. Accepts a mouse symbol/MGI id OR "
            "a human symbol/HGNC id (resolved to the mouse marker first). "
            "Signature: get_marker_ortholog(query, response_mode=)."
        ),
    )
    async def get_marker_ortholog(
        query: QueryStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_ortholog(query, response_mode)
            payload["_meta"] = {"next_commands": after_ortholog(payload)}
            return payload

        return await run_mcp_tool(
            "get_marker_ortholog",
            call,
            context=McpErrorContext("get_marker_ortholog", arguments={"query": query}),
        )

    @mcp.tool(
        name="get_marker_diseases",
        title="Get Marker Disease Models",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"disease"},
        description=(
            "Return the human-mouse disease models associated with a marker (Disease "
            "Ontology id + name + OMIM ids), from MGI's curated DO annotations. "
            "Accepts a mouse symbol/MGI id or a human ortholog. "
            "Signature: get_marker_diseases(query)."
        ),
    )
    async def get_marker_diseases(query: QueryStr) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_diseases(query)
            payload["_meta"] = {"next_commands": after_diseases(payload)}
            return payload

        return await run_mcp_tool(
            "get_marker_diseases",
            call,
            context=McpErrorContext("get_marker_diseases", arguments={"query": query}),
        )
