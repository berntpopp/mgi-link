"""Marker tools: resolve_marker, get_marker, search_markers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from mgi_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from mgi_link.mcp.envelope import McpErrorContext, run_mcp_tool
from mgi_link.mcp.next_commands import after_get_marker, after_resolve, after_search
from mgi_link.mcp.schemas import MARKER_SCHEMA, RESOLVE_SCHEMA, SEARCH_SCHEMA
from mgi_link.mcp.service_adapters import get_mgi_service
from mgi_link.mcp.tools._common import QueryStr, ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_marker_tools(mcp: FastMCP) -> None:
    """Register marker resolution / record / search tools."""

    @mcp.tool(
        name="resolve_marker",
        title="Resolve Mouse Marker",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=RESOLVE_SCHEMA,
        tags={"resolve"},
        description=(
            "Resolve any mouse marker reference to its canonical MGI record. Accepts "
            "a mouse symbol (current or synonym, case-insensitive), an MGI id "
            "(MGI:98968 or 98968), OR a human gene symbol / HGNC id (resolved to the "
            "mouse ortholog). Returns {mgi_id, symbol, name, marker_type, match_type "
            "(mgi_id|current|synonym|ortholog)}. An ambiguous symbol returns an "
            "ambiguous_query error with the candidate list (not silently picked). A "
            "human symbol identical to the mouse symbol resolves as match_type=current "
            "(case collision) rather than ortholog; the marker is the same. "
            "Signature: resolve_marker(query, response_mode=)."
        ),
    )
    async def resolve_marker(
        query: QueryStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().resolve(query, response_mode)
            payload["_meta"] = {"next_commands": after_resolve(payload)}
            return payload

        return await run_mcp_tool(
            "resolve_marker",
            call,
            context=McpErrorContext("resolve_marker", arguments={"query": query}),
        )

    @mcp.tool(
        name="get_marker",
        title="Get Marker Record",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=MARKER_SCHEMA,
        tags={"marker"},
        description=(
            "Return the full MGI marker record, resolved from an MGI id, mouse "
            "symbol/synonym, or human ortholog. Includes name, marker/feature type, "
            "GRCm39 location, NCBI/Ensembl ids, synonyms, the human ortholog "
            "(symbol/HGNC/OMIM), and summary counts (alleles, phenotypes, phenotype "
            "references, diseases). response_mode controls verbosity. "
            "Signature: get_marker(query, response_mode=)."
        ),
    )
    async def get_marker(
        query: QueryStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_marker(query, response_mode)
            payload["_meta"] = {"next_commands": after_get_marker(payload)}
            return payload

        return await run_mcp_tool(
            "get_marker",
            call,
            context=McpErrorContext("get_marker", arguments={"query": query}),
        )

    @mcp.tool(
        name="search_markers",
        title="Search Markers",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=SEARCH_SCHEMA,
        tags={"marker"},
        description=(
            "Free-text search over mouse marker symbols, names, and synonyms (FTS, "
            "relevance-ranked). Returns ranked {mgi_id, symbol, name, marker_type, "
            "score, match} summaries. Exact symbol/synonym hits are PINNED first "
            "(match: exact_symbol|exact_synonym|fts) so an exact gene is never buried "
            "under transgenes or lncRNAs. Returns a truncation contract {total, "
            "returned, limit, truncated}; when truncated, next_commands includes a "
            "widen step. marker_type optionally restricts to a type (e.g. 'Gene'). "
            "Nomenclature-only: no phenotype semantics — use search_phenotype_terms + "
            "find_markers_by_phenotype for phenotype-driven discovery, or "
            "resolve_marker for an exact symbol/id. "
            "Signature: search_markers(query, marker_type=, limit=, response_mode=)."
        ),
    )
    async def search_markers(
        query: Annotated[
            str, Field(description="Free-text query (symbol fragment, name, synonym).")
        ],
        marker_type: Annotated[
            str | None, Field(description="Optional marker type filter, e.g. 'Gene'.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Max hits (default 25).")] = 25,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().search(
                query, marker_type=marker_type, limit=limit, mode=response_mode
            )
            payload["_meta"] = {"next_commands": after_search(query, payload)}
            return payload

        return await run_mcp_tool(
            "search_markers",
            call,
            context=McpErrorContext("search_markers", arguments={"query": query}),
        )
