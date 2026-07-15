"""Discovery tools: get_server_capabilities, get_diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from mgi_link.buildinfo import build_info
from mgi_link.config import settings
from mgi_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from mgi_link.mcp.capabilities import collect_tool_signatures, project_capabilities
from mgi_link.mcp.envelope import McpErrorContext, run_mcp_tool
from mgi_link.mcp.next_commands import cmd
from mgi_link.mcp.service_adapters import get_mgi_service
from mgi_link.redaction import redact_url

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_discovery_tools(mcp: FastMCP) -> None:
    """Register discovery tools on a FastMCP instance."""

    @mcp.tool(
        name="get_server_capabilities",
        title="Get Server Capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"discovery"},
        description=(
            "Return the mgi-link discovery surface. detail='summary' (default) is "
            "light: identity/build/MGI release, the tool list WITH call signatures, "
            "accepted argument aliases, response modes, recommended workflows, error "
            "taxonomy, and limits. detail='full' adds vocabularies (allele types, "
            "marker types, match types) and the ortholog field catalogue. Call this "
            "first in a cold session, or read mgi://tools / mgi://capabilities. "
            "Signature: get_server_capabilities(detail=)."
        ),
    )
    async def get_server_capabilities(
        detail: Annotated[
            Literal["summary", "full"],
            Field(description="summary (default, light) or full (adds vocabularies)."),
        ] = "summary",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            signatures = await collect_tool_signatures(mcp)
            return project_capabilities(detail, signatures)

        return await run_mcp_tool(
            "get_server_capabilities",
            call,
            context=McpErrorContext("get_server_capabilities"),
        )

    @mcp.tool(
        name="get_diagnostics",
        title="Get MGI Diagnostics",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"discovery"},
        description=(
            "Report the local MGI index status: whether the data is built, the "
            "loaded release, marker/allele/phenotype/ortholog/disease counts, schema "
            "version, and when it was built. Use this to confirm freshness or "
            "diagnose a data_unavailable error. "
            "Signature: get_diagnostics()."
        ),
    )
    async def get_diagnostics() -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mgi_service().get_diagnostics()
            payload["build"] = build_info()
            payload["live_fallback"] = {
                "enabled": settings.mousemine.enable_live_fallback,
                # Redacted: an operator-configured URL may embed credentials/tokens.
                "base_url": redact_url(settings.mousemine.base_url),
            }
            payload["_meta"] = {
                "next_commands": [cmd("resolve_marker", query="Wt1")]
                if payload.get("data_available")
                else [cmd("get_server_capabilities")]
            }
            return payload

        return await run_mcp_tool(
            "get_diagnostics",
            call,
            context=McpErrorContext("get_diagnostics"),
        )
