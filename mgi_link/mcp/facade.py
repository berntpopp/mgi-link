"""MCP facade for mgi-link."""

from __future__ import annotations

from fastmcp import FastMCP

from mgi_link import __version__
from mgi_link.mcp.capabilities import register_capability_resources
from mgi_link.mcp.middleware import ArgValidationMiddleware
from mgi_link.mcp.notfound_guard import (
    NotFoundGuard,
    install_notfound_log_filter,
    install_protocol_error_handler,
)
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
        # Tool-Surface Budget v1: emit compact input schemas (no $ref expansion). Safe
        # here — no INPUT schema contains a $ref — and it trims the advertised surface.
        dereference_schemas=False,
    )

    register_discovery_tools(mcp)
    register_marker_tools(mcp)
    register_allele_tools(mcp)
    register_phenotype_tools(mcp)
    register_ortholog_tools(mcp)
    register_ontology_tools(mcp)
    register_capability_resources(mcp)
    # NotFoundGuard is added FIRST so its Layer-1 tool preflight is the OUTERMOST
    # middleware: an unknown tool name is answered with a fixed, name-free envelope
    # before ArgValidationMiddleware (Layer 4) or core dispatch can reflect it.
    mcp.add_middleware(NotFoundGuard())
    mcp.add_middleware(ArgValidationMiddleware())

    # Layer 3 -- protocol backstop: wrap the raw tool/resource/prompt request
    # handlers as the OUTERMOST guard so FastMCP core cannot reflect a
    # caller-supplied name/URI/prompt name (nor its code points) into a not-found
    # JSON-RPC error frame (notably the unknown-PROMPT echo). Installed last, after
    # all handlers exist.
    install_protocol_error_handler(mcp)
    # Layer 5 -- attach the validation-log scrub filter to FastMCP's own
    # non-propagating Rich handlers (and the root/mcp source loggers) now that they
    # exist, so the caller-supplied name/URI never reaches a log sink at ANY level.
    install_notfound_log_filter()

    return mcp
