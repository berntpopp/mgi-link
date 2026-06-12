"""Phenotype tools: get_marker_phenotypes, get_phenotype_overview, find_markers_by_phenotype."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from mgi_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from mgi_link.mcp.envelope import McpErrorContext, run_mcp_tool
from mgi_link.mcp.next_commands import after_find_by_pheno, after_overview, after_phenotypes
from mgi_link.mcp.schemas import FIND_MARKERS_SCHEMA, OVERVIEW_SCHEMA, PHENOTYPES_SCHEMA
from mgi_link.mcp.service_adapters import get_mgi_service
from mgi_link.mcp.tools._common import MpIdStr, QueryStr, ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_phenotype_tools(mcp: FastMCP) -> None:
    """Register phenotype tools (the gene-page Phenotypes section)."""

    @mcp.tool(
        name="get_marker_phenotypes",
        title="Get Marker Phenotypes",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=PHENOTYPES_SCHEMA,
        tags={"phenotype"},
        description=(
            "Return the Mammalian Phenotype (MP) annotations for a mouse marker — "
            "the gene page's Phenotypes section. By default (minimal/compact/standard) "
            "returns a DEDUPLICATED, support-ordered list of DISTINCT MP terms — each "
            "{mp_id, mp_term, genotype_count} (standard adds systems[]) — so the most "
            "replicated phenotypes come first and none are buried alphabetically. "
            "response_mode=full returns the per-genotype rows {mp_id, mp_term, "
            "allelic_composition, genetic_background, pubmed_id, genotype_id, ...}. "
            "Every response carries a phenotype summary and a truncation contract "
            "{total, returned, limit, truncated}; when truncated, next_commands "
            "includes a widen step. mp_system optionally restricts to one top-level "
            "system (name like 'renal/urinary system' or its MP id). Annotations are "
            "single-gene genotypes (MGI_GenePheno). "
            "Signature: get_marker_phenotypes(query, mp_system=, limit=, response_mode=)."
        ),
    )
    async def get_marker_phenotypes(
        query: QueryStr,
        mp_system: Annotated[
            str | None,
            Field(description="Optional top-level MP system filter (name or MP id)."),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=1000,
                description="Max rows — distinct terms, or genotype rows in full mode (default 250).",
            ),
        ] = 250,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_phenotypes(
                query, mp_system=mp_system, limit=limit, mode=response_mode
            )
            payload["_meta"] = {"next_commands": after_phenotypes(payload)}
            return payload

        return await run_mcp_tool(
            "get_marker_phenotypes",
            call,
            context=McpErrorContext("get_marker_phenotypes", arguments={"query": query}),
        )

    @mcp.tool(
        name="get_phenotype_overview",
        title="Get Phenotype Overview Grid",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=OVERVIEW_SCHEMA,
        tags={"phenotype"},
        description=(
            "Return the gene page's 'Phenotype Overview' grid: for each top-level MP "
            "system annotated for the marker (adipose tissue, cardiovascular system, "
            "renal/urinary system, nervous system, neoplasm, vision/eye, ...), the "
            "distinct annotated MP terms rolled up via the MP ontology. Use this for "
            "the system-level overview, then get_marker_phenotypes(mp_system=) to "
            "drill into one system. "
            "Signature: get_phenotype_overview(query)."
        ),
    )
    async def get_phenotype_overview(query: QueryStr) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_phenotype_overview(query)
            payload["_meta"] = {"next_commands": after_overview(payload)}
            return payload

        return await run_mcp_tool(
            "get_phenotype_overview",
            call,
            context=McpErrorContext("get_phenotype_overview", arguments={"query": query}),
        )

    @mcp.tool(
        name="find_markers_by_phenotype",
        title="Find Markers by Phenotype",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=FIND_MARKERS_SCHEMA,
        tags={"phenotype", "reverse"},
        description=(
            "Reverse lookup: return the mouse markers (genes) annotated with a "
            "Mammalian Phenotype term. include_descendants defaults to TRUE and "
            "changes WHICH genes are returned: it rolls up annotations to "
            "more-specific child terms via the MP ontology (e.g. MP:0005367 "
            "renal/urinary system phenotype gathers all kidney phenotypes); the flag "
            "is echoed in the response. Returns a truncation contract {total, "
            "returned, limit, truncated}; when truncated, next_commands includes a "
            "widen step. Resolve a term first with search_phenotype_terms. "
            "Signature: find_markers_by_phenotype(mp_id, include_descendants=, limit=)."
        ),
    )
    async def find_markers_by_phenotype(
        mp_id: MpIdStr,
        include_descendants: Annotated[
            bool, Field(description="Also include child (more specific) MP terms (default true).")
        ] = True,
        limit: Annotated[int, Field(ge=1, le=500, description="Max markers (default 100).")] = 100,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().find_markers_by_phenotype(
                mp_id, include_descendants=include_descendants, limit=limit
            )
            payload["_meta"] = {"next_commands": after_find_by_pheno(payload)}
            return payload

        return await run_mcp_tool(
            "find_markers_by_phenotype",
            call,
            context=McpErrorContext("find_markers_by_phenotype", arguments={"mp_id": mp_id}),
        )
