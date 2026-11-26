"""Shared annotated argument types for the MCP tools."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(description="Verbosity: minimal | compact | standard | full (default compact)."),
]

QueryStr = Annotated[
    str,
    Field(
        description="A mouse marker symbol (current or synonym, case-insensitive), an MGI id "
        "(MGI:98968 or 98968), or a human gene symbol / HGNC id / NCBIGene:<id> for the ortholog. "
        "A human Ensembl id (ENSG...) is rejected: convert it with hgnc_resolve_symbol first.",
        examples=["Wt1", "MGI:98968", "Pax6", "WT1", "HGNC:12796"],
    ),
]

MpIdStr = Annotated[
    str,
    Field(
        description="A Mammalian Phenotype term id (MP:0005367).",
        examples=["MP:0005367", "MP:0002080", "MP:0000601"],
    ),
]
