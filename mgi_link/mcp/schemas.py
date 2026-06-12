"""JSON output schemas for the typed MCP tools (MCP structured output).

The schemas are deliberately **permissive** (``additionalProperties: true``,
nothing ``required``) because ``response_mode`` projects fields out and the error
envelope is returned by the same tool body and must also validate.
"""

from __future__ import annotations

from typing import Any

_META = {"type": "object", "additionalProperties": True}


def _envelope(**properties: Any) -> dict[str, Any]:
    """A permissive object schema carrying the common envelope keys + extras."""
    props: dict[str, Any] = {
        "success": {"type": "boolean"},
        "_meta": _META,
        "error_code": {"type": "string"},
        "message": {"type": "string"},
        "retryable": {"type": "boolean"},
        "recovery_action": {"type": "string"},
        "field": {"type": "string"},
        "allowed_values": {"type": "array"},
        "hint": {"type": "string"},
        "candidates": {"type": "array"},
        **properties,
    }
    return {"type": "object", "additionalProperties": True, "properties": props}


_STR = {"type": "string"}
_STR_NULL = {"type": ["string", "null"]}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}
_ARR = {"type": "array"}
_OBJ = {"type": "object", "additionalProperties": True}

CAPABILITIES_SCHEMA = _envelope(
    server=_STR,
    server_version=_STR,
    mgi_release=_STR,
    tools=_ARR,
    response_modes=_ARR,
    error_codes=_ARR,
)

DIAGNOSTICS_SCHEMA = _envelope(
    data_available=_BOOL,
    release=_STR_NULL,
    marker_count=_INT,
    allele_count=_INT,
    genopheno_count=_INT,
    mp_term_count=_INT,
    ortholog_count=_INT,
    disease_count=_INT,
    built_utc=_STR,
    build=_OBJ,
)

RESOLVE_SCHEMA = _envelope(
    query=_STR,
    mgi_id=_STR_NULL,
    symbol=_STR_NULL,
    name=_STR_NULL,
    marker_type=_STR_NULL,
    feature_type=_STR_NULL,
    location=_STR_NULL,
    match_type=_STR_NULL,
)

MARKER_SCHEMA = _envelope(
    mgi_id=_STR,
    symbol=_STR,
    name=_STR_NULL,
    marker_type=_STR_NULL,
    feature_type=_STR_NULL,
    location=_STR_NULL,
    chromosome=_STR_NULL,
    entrez_id=_STR_NULL,
    ensembl_gene_id=_STR_NULL,
    synonyms=_ARR,
    human_ortholog=_OBJ,
    summary=_OBJ,
    match_type=_STR,
    requested_query=_STR,
)

SEARCH_SCHEMA = _envelope(
    query=_STR,
    marker_type=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    truncated=_BOOL,
    results=_ARR,
)

ALLELES_SCHEMA = _envelope(
    mgi_id=_STR,
    symbol=_STR,
    allele_type_filter=_STR_NULL,
    total_alleles=_INT,
    category_counts=_OBJ,
    total=_INT,
    returned=_INT,
    limit=_INT,
    truncated=_BOOL,
    alleles=_ARR,
)

PHENOTYPES_SCHEMA = _envelope(
    mgi_id=_STR,
    symbol=_STR,
    mp_system_filter=_STR_NULL,
    view=_STR,
    summary=_OBJ,
    total=_INT,
    returned=_INT,
    limit=_INT,
    truncated=_BOOL,
    annotations=_ARR,
)

OVERVIEW_SCHEMA = _envelope(
    mgi_id=_STR,
    symbol=_STR,
    summary=_OBJ,
    system_count=_INT,
    systems=_ARR,
)

DISEASES_SCHEMA = _envelope(mgi_id=_STR, symbol=_STR, count=_INT, diseases=_ARR)

ORTHOLOG_SCHEMA = _envelope(
    mgi_id=_STR,
    mouse_symbol=_STR,
    match_type=_STR,
    has_ortholog=_BOOL,
    ortholog=_OBJ,
)

MP_TERM_SCHEMA = _envelope(
    mp_id=_STR,
    name=_STR,
    definition=_STR_NULL,
    parents=_ARR,
    children=_ARR,
    top_level_systems=_ARR,
)

MP_SEARCH_SCHEMA = _envelope(
    query=_STR, total=_INT, returned=_INT, limit=_INT, truncated=_BOOL, results=_ARR
)

FIND_MARKERS_SCHEMA = _envelope(
    mp_id=_STR,
    mp_term=_STR,
    include_descendants=_BOOL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    truncated=_BOOL,
    markers=_ARR,
)
