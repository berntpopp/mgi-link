"""Ontology tools: get_mp_term, search_phenotype_terms."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from mgi_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from mgi_link.mcp.envelope import McpErrorContext, run_mcp_tool
from mgi_link.mcp.next_commands import after_mp_term, after_search_terms
from mgi_link.mcp.schemas import MP_SEARCH_SCHEMA, MP_TERM_SCHEMA
from mgi_link.mcp.service_adapters import get_mgi_service
from mgi_link.mcp.tools._common import MpIdStr

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_ontology_tools(mcp: FastMCP) -> None:
    """Register Mammalian Phenotype ontology tools."""

    @mcp.tool(
        name="get_mp_term",
        title="Get Mammalian Phenotype Term",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=MP_TERM_SCHEMA,
        tags={"ontology", "phenotype"},
        description=(
            "Return a Mammalian Phenotype (MP) ontology term: id, name, definition, "
            "direct parents and children (is_a edges), and the top-level system(s) it "
            "rolls up to. Use with find_markers_by_phenotype to go from a phenotype "
            "to the mouse genes that model it. "
            "Signature: get_mp_term(mp_id)."
        ),
    )
    async def get_mp_term(mp_id: MpIdStr) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_mp_term(mp_id)
            payload["_meta"] = {"next_commands": after_mp_term(payload)}
            return payload

        return await run_mcp_tool(
            "get_mp_term",
            call,
            context=McpErrorContext("get_mp_term", arguments={"mp_id": mp_id}),
        )

    @mcp.tool(
        name="search_phenotype_terms",
        title="Search Mammalian Phenotype Terms",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=MP_SEARCH_SCHEMA,
        tags={"ontology", "phenotype"},
        description=(
            "Free-text search over Mammalian Phenotype (MP) term names and "
            "definitions (FTS, relevance-ranked). Returns {mp_id, name, definition, "
            "score} plus a truncation contract {total, returned, limit, truncated} "
            "(widen step in next_commands when truncated). Use this to resolve a "
            "phenotype description to an MP id, then find_markers_by_phenotype or "
            "get_mp_term. "
            "Signature: search_phenotype_terms(query, limit=)."
        ),
    )
    async def search_phenotype_terms(
        query: Annotated[
            str, Field(description="Free-text phenotype query (e.g. 'small kidney').")
        ],
        limit: Annotated[int, Field(ge=1, le=200, description="Max hits (default 25).")] = 25,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().search_phenotype_terms(query, limit=limit)
            payload["_meta"] = {"next_commands": after_search_terms(query, payload)}
            return payload

        return await run_mcp_tool(
            "search_phenotype_terms",
            call,
            context=McpErrorContext("search_phenotype_terms", arguments={"query": query}),
        )
