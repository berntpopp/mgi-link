"""Allele tools: get_marker_alleles (Mutations & Alleles)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from mgi_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from mgi_link.mcp.envelope import McpErrorContext, run_mcp_tool
from mgi_link.mcp.next_commands import after_alleles
from mgi_link.mcp.schemas import ALLELES_SCHEMA
from mgi_link.mcp.service_adapters import get_mgi_service
from mgi_link.mcp.tools._common import QueryStr, ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_allele_tools(mcp: FastMCP) -> None:
    """Register allele / mutation tools."""

    @mcp.tool(
        name="get_marker_alleles",
        title="Get Marker Alleles & Mutations",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=ALLELES_SCHEMA,
        tags={"allele", "mutation"},
        description=(
            "Return the phenotypic alleles / mutations for a mouse marker — the gene "
            "page's 'All Mutations and Alleles' panel. Includes per-allele "
            "{allele_id, symbol, name, allele_type, attributes, pubmed_ids} and the "
            "generation-method category_counts (Targeted, Endonuclease-mediated, "
            "Radiation induced, Chemically induced, Transgenic, ...). allele_type "
            "optionally filters (accepts friendly tokens like 'knockout', 'crispr', "
            "'targeted'). Returns a truncation contract {total, returned, limit, "
            "truncated}; when truncated, next_commands includes a widen step. "
            "Signature: get_marker_alleles(query, allele_type=, limit=, response_mode=)."
        ),
    )
    async def get_marker_alleles(
        query: QueryStr,
        allele_type: Annotated[
            str | None,
            Field(
                description="Optional allele-type filter (e.g. 'Targeted', 'knockout', 'crispr')."
            ),
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=1000, description="Max alleles returned (default 200).")
        ] = 200,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_alleles(
                query, allele_type=allele_type, limit=limit, mode=response_mode
            )
            payload["_meta"] = {"next_commands": after_alleles(payload)}
            return payload

        return await run_mcp_tool(
            "get_marker_alleles",
            call,
            context=McpErrorContext("get_marker_alleles", arguments={"query": query}),
        )
