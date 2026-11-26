"""Builders for `_meta.next_commands` entries: `{tool, arguments}` steps."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from mgi_link.identifiers import (
    infer_xref_source,
    looks_like_mgi_id,
    looks_like_mp_id,
    looks_like_symbol,
    normalize_mp_id,
)

_HGNC_RE = re.compile(r"^HGNC:\d+$", re.IGNORECASE)


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def _safe_recovery_query(value: str) -> str | None:
    """Return the caller value ONLY if it matches an exact identifier grammar.

    An error-path recovery command echoes the failed query back into a
    ``next_commands`` argument. Free-form query text can carry injection prose
    (which code-point stripping does NOT remove), so it is echoed ONLY when it
    provably conforms to a marker/MP identifier or gene-symbol grammar (no spaces,
    no forbidden code points); otherwise it is omitted and the caller falls back
    to a generic ``get_server_capabilities`` recovery.
    """
    text = (value or "").strip()
    if (
        looks_like_mgi_id(text)
        or looks_like_mp_id(text)
        or looks_like_symbol(text)
        or _HGNC_RE.match(text)
    ):
        return text
    return None


def echo_safe(query: str) -> str | None:
    """Caller free text fit to repeat in a page/widen step of the same call (GTS-CORE-TXT-04).

    Kept only if at most 200 characters with no control/format (Cc/Cf) code point.
    """
    if len(query) > 200 or any(unicodedata.category(ch) in ("Cc", "Cf") for ch in query):
        return None
    return query


def widen_cmd(tool: str, base_args: dict[str, Any], total: int, ceiling: int) -> dict[str, Any]:
    """A ready-to-call step that re-runs ``tool`` with ``limit`` raised to fit."""
    return cmd(tool, **{**base_args, "limit": min(total, ceiling)})


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback."""
    if tool in ("resolve_marker", "get_marker", "get_marker_alleles", "get_marker_phenotypes"):
        # Echo the failed query into a recovery command ONLY if it is a valid
        # identifier/symbol shape; a free-form (prose) query is omitted.
        value = _safe_recovery_query(str(arguments.get("query", "")))
        if value is not None:
            if infer_xref_source(value):
                return [cmd("resolve_marker", query=value), cmd("search_markers", query=value)]
            if looks_like_symbol(value) or not looks_like_mgi_id(value):
                return [cmd("search_markers", query=value), cmd("get_server_capabilities")]
    if tool in ("get_mp_term", "find_markers_by_phenotype"):
        # normalize_mp_id returns the canonical MP:NNNNNNN form or None (rejecting
        # any non-conforming/prose mp_id), so the echoed query is always validated.
        value = normalize_mp_id(str(arguments.get("mp_id", "")))
        return (
            [cmd("search_phenotype_terms", query=value)]
            if value
            else [cmd("get_server_capabilities")]
        )
    if error_code == "upstream_unavailable":
        # The local index being unbuilt/unreadable classifies as upstream_unavailable
        # (data dependency down); get_diagnostics reports the build/refresh state.
        return [cmd("get_diagnostics")]
    return [cmd("get_server_capabilities")]


def after_resolve(resolution: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_marker: drill into the marker record + phenotypes.

    Live (MouseMine) results steer to get_marker + diagnostics, never the
    aggregate tools, which are data_unavailable while the index is cold.
    """
    mgi_id = resolution.get("mgi_id")
    if not mgi_id:
        value = _safe_recovery_query(str(resolution.get("query", "")))
        if value is None:
            return [cmd("get_server_capabilities")]
        return [cmd("search_markers", query=value)]
    if resolution.get("source") == "mousemine":
        return [cmd("get_marker", query=mgi_id), cmd("get_diagnostics")]
    return [
        cmd("get_marker", query=mgi_id),
        cmd("get_marker_phenotypes", query=mgi_id),
    ]


def after_get_marker(marker: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker: offer alleles + the phenotype overview grid.

    Live (MouseMine) results steer to diagnostics/capabilities instead.
    """
    mgi_id = marker.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    if marker.get("source") == "mousemine":
        return [cmd("get_diagnostics"), cmd("get_server_capabilities")]
    return [
        cmd("get_marker_alleles", query=mgi_id),
        cmd("get_phenotype_overview", query=mgi_id),
    ]


def after_search(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After search_markers: open the top hit; widen if truncated."""
    hits = payload.get("results", [])
    if not hits:
        # Forward the query to another tool only once it passed identifier validation.
        value = _safe_recovery_query(query)
        if value is None:
            return [cmd("get_server_capabilities")]
        return [cmd("resolve_marker", query=value), cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = hits[0].get("mgi_id")
    if top:
        steps.append(cmd("get_marker", query=top))
    if payload.get("truncated") and (safe := echo_safe(query)) is not None:
        steps.append(
            widen_cmd("search_markers", {"query": safe}, int(payload.get("total", 0)), 200)
        )
    return steps or [cmd("get_server_capabilities")]


def after_alleles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker_alleles: widen if truncated, then phenotypes + overview."""
    mgi_id = payload.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    if payload.get("truncated"):
        steps.append(
            widen_cmd("get_marker_alleles", {"query": mgi_id}, int(payload.get("total", 0)), 1000)
        )
    steps += [
        cmd("get_marker_phenotypes", query=mgi_id),
        cmd("get_phenotype_overview", query=mgi_id),
    ]
    return steps


def after_phenotypes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker_phenotypes: widen if truncated, then overview + diseases."""
    mgi_id = payload.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    if payload.get("truncated"):
        steps.append(
            widen_cmd(
                "get_marker_phenotypes", {"query": mgi_id}, int(payload.get("total", 0)), 1000
            )
        )
    steps += [cmd("get_phenotype_overview", query=mgi_id), cmd("get_marker_diseases", query=mgi_id)]
    return steps


def after_overview(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_phenotype_overview: zoom into the first annotated system."""
    mgi_id = payload.get("mgi_id")
    systems = payload.get("systems", [])
    if mgi_id and systems:
        return [cmd("get_marker_phenotypes", query=mgi_id, mp_system=systems[0]["system"])]
    if mgi_id:
        return [cmd("get_marker_alleles", query=mgi_id)]
    return [cmd("get_server_capabilities")]


def after_ortholog(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker_ortholog: offer disease models + phenotypes."""
    mgi_id = payload.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_marker_diseases", query=mgi_id), cmd("get_marker_phenotypes", query=mgi_id)]


def after_diseases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker_diseases: offer the ortholog + phenotypes."""
    mgi_id = payload.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_marker_ortholog", query=mgi_id), cmd("get_marker_phenotypes", query=mgi_id)]


def after_mp_term(term: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_mp_term: find markers annotated with it, or a child term."""
    mp_id = term.get("mp_id")
    if not mp_id:
        return [cmd("get_server_capabilities")]
    return [cmd("find_markers_by_phenotype", mp_id=mp_id)]


def after_search_terms(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After search_phenotype_terms: open the top term; widen if truncated."""
    hits = payload.get("results", [])
    if not hits:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = hits[0].get("mp_id")
    if top:
        steps.append(cmd("get_mp_term", mp_id=top))
    if payload.get("truncated") and (safe := echo_safe(query)) is not None:
        steps.append(
            widen_cmd("search_phenotype_terms", {"query": safe}, int(payload.get("total", 0)), 200)
        )
    return steps or [cmd("get_server_capabilities")]


def after_find_by_pheno(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After find_markers_by_phenotype: widen if truncated, else open first marker."""
    markers = payload.get("markers", [])
    steps: list[dict[str, Any]] = []
    if payload.get("truncated") and payload.get("mp_id"):
        steps.append(
            widen_cmd(
                "find_markers_by_phenotype",
                {"mp_id": payload["mp_id"]},
                int(payload.get("total", 0)),
                500,
            )
        )
    if markers and markers[0].get("mgi_id"):
        steps.append(cmd("get_marker_phenotypes", query=markers[0]["mgi_id"]))
    return steps or [cmd("get_server_capabilities")]


def withdrawn_recovery(replaced_by: list[dict[str, str]]) -> list[dict[str, Any]]:
    """After a withdrawn-entry error: chain to the successor record(s)."""
    targets = [r.get("mgi_id") for r in replaced_by if r.get("mgi_id")]
    if not targets:
        return [cmd("get_server_capabilities")]
    return [cmd("get_marker", query=t) for t in targets[:2]]
