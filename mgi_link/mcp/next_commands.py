"""Builders for `_meta.next_commands` entries: `{tool, arguments}` steps."""

from __future__ import annotations

from typing import Any

from mgi_link.identifiers import infer_xref_source, looks_like_mgi_id, looks_like_symbol


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def widen_cmd(tool: str, base_args: dict[str, Any], total: int, ceiling: int) -> dict[str, Any]:
    """A ready-to-call step that re-runs ``tool`` with ``limit`` raised to fit."""
    return cmd(tool, **{**base_args, "limit": min(total, ceiling)})


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback."""
    if tool in ("resolve_marker", "get_marker", "get_marker_alleles", "get_marker_phenotypes"):
        value = str(arguments.get("query", ""))
        source = infer_xref_source(value)
        if source:
            return [cmd("resolve_marker", query=value), cmd("search_markers", query=value)]
        if value and (looks_like_symbol(value) or not looks_like_mgi_id(value)):
            return [cmd("search_markers", query=value), cmd("get_server_capabilities")]
    if tool in ("get_mp_term", "find_markers_by_phenotype"):
        value = str(arguments.get("mp_id", ""))
        return (
            [cmd("search_phenotype_terms", query=value)]
            if value
            else [cmd("get_server_capabilities")]
        )
    if error_code == "data_unavailable":
        return [cmd("get_mgi_diagnostics")]
    return [cmd("get_server_capabilities")]


def after_resolve(resolution: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_marker: drill into the marker record + phenotypes."""
    mgi_id = resolution.get("mgi_id")
    if not mgi_id:
        return [cmd("search_markers", query=str(resolution.get("query", "")))]
    return [
        cmd("get_marker", query=mgi_id),
        cmd("get_marker_phenotypes", query=mgi_id),
    ]


def after_get_marker(marker: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_marker: offer alleles + the phenotype overview grid."""
    mgi_id = marker.get("mgi_id")
    if not mgi_id:
        return [cmd("get_server_capabilities")]
    return [
        cmd("get_marker_alleles", query=mgi_id),
        cmd("get_phenotype_overview", query=mgi_id),
    ]


def after_search(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After search_markers: open the top hit; widen if truncated."""
    hits = payload.get("results", [])
    if not hits:
        return [cmd("resolve_marker", query=query), cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = hits[0].get("mgi_id")
    if top:
        steps.append(cmd("get_marker", query=top))
    if payload.get("truncated"):
        steps.append(
            widen_cmd("search_markers", {"query": query}, int(payload.get("total", 0)), 200)
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
    if payload.get("truncated"):
        steps.append(
            widen_cmd("search_phenotype_terms", {"query": query}, int(payload.get("total", 0)), 200)
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
