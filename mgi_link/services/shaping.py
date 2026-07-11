"""Response-mode projection for MGI payloads.

``standard`` / ``full`` are the identity (the complete record). ``compact`` (the
default) drops null/empty values and a few verbose fields. ``minimal`` keeps only
the identity anchors.
"""

from __future__ import annotations

from typing import Any

from mgi_link.mcp.untrusted_content import UntrustedText, fence_untrusted_text

RESPONSE_MODES: tuple[str, ...] = ("minimal", "compact", "standard", "full")
DEFAULT_RESPONSE_MODE = "compact"

_PRESERVE_KEYS: frozenset[str] = frozenset({"_meta", "success"})

# Verbose marker fields dropped in compact mode.
_MARKER_DROP_COMPACT: frozenset[str] = frozenset({"cm_position", "status"})

_MARKER_KEEP_MINIMAL: frozenset[str] = frozenset(
    {
        "mgi_id",
        "symbol",
        "name",
        "marker_type",
        "match_type",
        "requested_query",
        "chromosome",
        "_meta",
    }
)

_RESOLUTION_MINIMAL: frozenset[str] = frozenset({"query", "mgi_id", "symbol", "match_type"})


def _drop_empty(record: dict[str, Any]) -> dict[str, Any]:
    """Drop null/empty values (keeping preserved keys)."""
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key not in _PRESERVE_KEYS and (
            value is None or value == [] or value == "" or value == {}
        ):
            continue
        out[key] = value
    return out


def shape_resolution(record: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a resolve_marker success payload to the requested verbosity."""
    if mode == "minimal":
        return {k: v for k, v in record.items() if k in _RESOLUTION_MINIMAL}
    if mode in ("standard", "full"):
        return record
    return _drop_empty(record)


def shape_marker(record: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a flat marker-record payload to the requested verbosity."""
    if mode in ("standard", "full"):
        return record
    if mode == "minimal":
        return {k: v for k, v in record.items() if k in _MARKER_KEEP_MINIMAL}
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key in _MARKER_DROP_COMPACT and key not in _PRESERVE_KEYS:
            continue
        if key not in _PRESERVE_KEYS and (value is None or value == [] or value == ""):
            continue
        out[key] = value
    return out


def shape_summary(summary: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a search/candidate summary row to the requested verbosity."""
    if mode == "minimal":
        keep = {"mgi_id", "symbol", "match_type", "symbol_type", "match"}
        return {k: v for k, v in summary.items() if k in keep}
    if mode in ("standard", "full"):
        return summary
    return {k: v for k, v in summary.items() if v is not None and v != ""}


def shape_allele(allele: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project an allele row to the requested verbosity."""
    if mode == "minimal":
        keep = {"allele_id", "symbol", "allele_type"}
        return {k: v for k, v in allele.items() if k in keep}
    if mode in ("standard", "full"):
        return allele
    return {k: v for k, v in allele.items() if v is not None and v != []}


def shape_phenotype_term(row: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a distinct-term phenotype row to the requested verbosity."""
    out: dict[str, Any] = {
        "mp_id": row["mp_id"],
        "mp_term": row["mp_term"],
        "genotype_count": row["genotype_count"],
    }
    if mode == "standard":
        out["systems"] = row.get("systems", [])
    return out


def shape_phenotype_genotype(row: dict[str, Any]) -> dict[str, Any]:
    """Per-genotype phenotype row (full view): the complete annotation."""
    return row


def fence_mp_definition(
    record: dict[str, Any], *, source: str, record_id: str
) -> tuple[dict[str, Any], UntrustedText | None]:
    """Fence a MP term/hit's ``definition`` into a typed ``UntrustedText`` object.

    Response-Envelope Standard v1.1: externally sourced MP-ontology prose is
    never returned as a bare string. Returns the reshaped record plus the fenced
    object (``None`` when there was no definition to fence) so the caller can
    batch limits enforcement across a whole response.
    """
    definition = record.get("definition")
    if not definition:
        return record, None
    fenced = fence_untrusted_text(definition, source=source, record_id=record_id)
    return {**record, "definition": fenced.model_dump(mode="json")}, fenced
