"""MCP facade for mgi-link."""

from __future__ import annotations

from fastmcp import FastMCP

from mgi_link import __version__
from mgi_link.mcp.capabilities import register_capability_resources
from mgi_link.mcp.middleware import ArgValidationMiddleware
from mgi_link.mcp.resources import MGI_SERVER_INSTRUCTIONS
from mgi_link.mcp.tools import (
    register_allele_tools,
    register_discovery_tools,
    register_marker_tools,
    register_ontology_tools,
    register_ortholog_tools,
    register_phenotype_tools,
)


def create_mgi_mcp() -> FastMCP:
    """Build a FastMCP instance with all mgi-link tools and resources."""
    mcp = FastMCP(
        name="mgi-link",
        version=__version__,
        instructions=MGI_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )

    register_discovery_tools(mcp)
    register_marker_tools(mcp)
    register_allele_tools(mcp)
    register_phenotype_tools(mcp)
    register_ortholog_tools(mcp)
    register_ontology_tools(mcp)
    register_capability_resources(mcp)
    mcp.add_middleware(ArgValidationMiddleware())

    return mcp
