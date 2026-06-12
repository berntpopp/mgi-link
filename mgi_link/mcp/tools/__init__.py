"""MCP tool registration entry points."""

from __future__ import annotations

from mgi_link.mcp.tools.alleles import register_allele_tools
from mgi_link.mcp.tools.discovery import register_discovery_tools
from mgi_link.mcp.tools.markers import register_marker_tools
from mgi_link.mcp.tools.ontology import register_ontology_tools
from mgi_link.mcp.tools.orthologs import register_ortholog_tools
from mgi_link.mcp.tools.phenotypes import register_phenotype_tools

__all__ = [
    "register_allele_tools",
    "register_discovery_tools",
    "register_marker_tools",
    "register_ontology_tools",
    "register_ortholog_tools",
    "register_phenotype_tools",
]
