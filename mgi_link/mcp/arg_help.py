"""Argument ergonomics for MCP tools: aliases, did-you-mean, signatures.

Pure functions with no FastMCP dependency so they unit-test in isolation. The
middleware and the discovery surface both consume them, keeping one source of
truth for what a "valid argument" looks like.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from typing import Any

# Curated synonym -> canonical map, scoped to this server's parameter space. An
# alias only ever resolves to a canonical name that is a *real* parameter of the
# tool being called (see ``normalize_alias_args``), so a shared map is safe.
ARG_ALIASES: dict[str, str] = {
    # query: the universal marker identifier slot (symbol, MGI id, or human ortholog)
    "symbol": "query",
    "gene": "query",
    "gene_symbol": "query",
    "marker": "query",
    "marker_symbol": "query",
    "mgi": "query",
    "mgi_id": "query",
    "id": "query",
    "identifier": "query",
    "hgnc": "query",
    "hgnc_id": "query",
    "q": "query",
    "text": "query",
    # MP term slot (get_mp_term, find_markers_by_phenotype)
    "mp": "mp_id",
    "mp_term": "mp_id",
    "mp_term_id": "mp_id",
    "phenotype": "mp_id",
    "phenotype_id": "mp_id",
    # MP system filter
    "system": "mp_system",
    "mp_system_name": "mp_system",
    # allele type filter
    "generation_method": "allele_type",
    "alleletype": "allele_type",
    # paging / verbosity
    "max": "limit",
    "top": "limit",
    "n": "limit",
    "mode": "response_mode",
    "verbosity": "response_mode",
    # reverse-pheno toggle
    "descendants": "include_descendants",
    "include_children": "include_descendants",
}


def normalize_alias_args(
    valid_params: Iterable[str], arguments: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Rewrite known alias keys to their canonical parameter names.

    An alias is applied only when (a) the alias key is present, (b) the canonical
    target is a real parameter of the called tool, and (c) the canonical key is not
    already supplied explicitly. Returns ``(new_arguments, applied_pairs)``.
    """
    valid = set(valid_params)
    result = dict(arguments)
    applied: list[tuple[str, str]] = []
    for alias, canonical in ARG_ALIASES.items():
        if alias in result and canonical in valid:
            if canonical in result:
                result.pop(alias)  # explicit canonical wins; drop the alias
            else:
                result[canonical] = result.pop(alias)
                applied.append((alias, canonical))
    return result, applied


def did_you_mean(unknown: str, valid: Iterable[str]) -> str | None:
    """Best canonical suggestion for an unknown argument name, or ``None``."""
    valid_list = list(valid)
    aliased = ARG_ALIASES.get(unknown)
    if aliased is not None and aliased in valid_list:
        return aliased
    matches = difflib.get_close_matches(unknown, valid_list, n=1, cutoff=0.6)
    return matches[0] if matches else None


def describe_constraints(field_schema: Mapping[str, Any]) -> tuple[list[str], str] | None:
    """Surface a field's enum/range for an invalid-*value* error.

    Returns ``(allowed_values, human_phrase)`` for an ``enum`` or a bounded
    numeric field (digging through ``anyOf``/``allOf``/``oneOf``), or ``None`` for
    a field with no value constraint (so the caller falls back to a name error).
    """
    nodes: list[Any] = [field_schema]
    for key in ("anyOf", "allOf", "oneOf"):
        nodes.extend(field_schema.get(key, []))
    for node in nodes:
        if isinstance(node, Mapping) and node.get("enum"):
            vals = [str(v) for v in node["enum"]]
            return vals, "must be one of: " + ", ".join(vals)
    lo: Any = None
    hi: Any = None
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        lo = node.get("minimum", node.get("exclusiveMinimum", lo))
        hi = node.get("maximum", node.get("exclusiveMaximum", hi))
    if lo is not None or hi is not None:
        lo_s = str(int(lo)) if lo is not None else "?"
        hi_s = str(int(hi)) if hi is not None else "?"
        return [f"{lo_s}..{hi_s}"], f"must be between {lo_s} and {hi_s}"
    min_items: Any = None
    max_items: Any = None
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        min_items = node.get("minItems", min_items)
        max_items = node.get("maxItems", max_items)
    if min_items is not None or max_items is not None:
        lo_s = str(int(min_items)) if min_items is not None else "0"
        hi_s = str(int(max_items)) if max_items is not None else "?"
        return [f"{lo_s}..{hi_s} items"], f"must have between {lo_s} and {hi_s} items"
    return None


def tool_signature(name: str, schema: Mapping[str, Any]) -> str:
    """Render ``name(req, opt=, ...)`` from a JSON input schema."""
    props = list(schema.get("properties", {}).keys())
    required = set(schema.get("required") or [])
    parts = [p for p in props if p in required]
    parts += [f"{p}=" for p in props if p not in required]
    return f"{name}(" + ", ".join(parts) + ")"
