"""Capabilities payload and mgi:// discovery resources."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mgi_link import __version__
from mgi_link.buildinfo import build_info
from mgi_link.config import settings
from mgi_link.constants import (
    ALLELE_TYPES,
    MARKER_TYPES,
    MATCH_TYPES,
    MGI_LICENSE,
    ORTHOLOG_XREF_FIELDS,
    RECOMMENDED_CITATION,
    XREF_SOURCE_ALIASES,
)
from mgi_link.ingest.builder import read_meta
from mgi_link.mcp.arg_help import ARG_ALIASES, tool_signature
from mgi_link.mcp.resources import (
    MGI_REFERENCE_NOTES,
    MGI_USAGE_NOTES,
    RESEARCH_USE_NOTICE,
)
from mgi_link.services.shaping import DEFAULT_RESPONSE_MODE, RESPONSE_MODES

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Reverse the alias map to {canonical: [accepted synonyms]} for human-facing docs.
_ALIAS_DOC: dict[str, list[str]] = {}
for _alias, _canonical in sorted(ARG_ALIASES.items()):
    _ALIAS_DOC.setdefault(_canonical, []).append(_alias)

_SUMMARY_KEYS: tuple[str, ...] = (
    "server",
    "server_version",
    "build",
    "mgi_release",
    "data_source",
    "research_use_only",
    "research_use_notice",
    "recommended_citation",
    "license",
    "tools",
    "tool_count",
    "response_modes",
    "default_response_mode",
    "recommended_workflows",
    "argument_alias_policy",
    "search_semantics",
    "truncation_contract",
    "response_mode_semantics",
    "behavioral_defaults",
    "field_glossary",
    "error_codes",
    "limits",
    "read_only",
)

TOOLS: list[str] = [
    "get_server_capabilities",
    "get_diagnostics",
    "resolve_marker",
    "get_marker",
    "search_markers",
    "get_marker_alleles",
    "get_marker_phenotypes",
    "get_phenotype_overview",
    "get_marker_diseases",
    "get_marker_ortholog",
    "get_mp_term",
    "search_phenotype_terms",
    "find_markers_by_phenotype",
]


def _mgi_release() -> str:
    """Best-effort loaded-release string (without forcing a DB build)."""
    meta = read_meta(settings.data.db_path)
    if meta is None:
        return "not-built"
    return meta.release or "unknown"


def build_capabilities() -> dict[str, Any]:
    """Return the discovery surface describing this server."""
    return {
        "server": "mgi-link",
        "server_version": __version__,
        "build": build_info(),
        "mgi_release": _mgi_release(),
        "data_source": (
            "Local SQLite index built from the MGI bulk data reports "
            "(MRK_List2, MGI_PhenotypicAllele, MGI_GenePheno, VOC_MammalianPhenotype, "
            "MPheno_OBO, HOM_MouseHumanSequence, MGI_DO), refreshed by cron."
        ),
        "research_use_only": True,
        "research_use_notice": RESEARCH_USE_NOTICE,
        "recommended_citation": RECOMMENDED_CITATION,
        "license": MGI_LICENSE,
        "tools": TOOLS,
        "tool_count": len(TOOLS),
        "response_modes": list(RESPONSE_MODES),
        "default_response_mode": DEFAULT_RESPONSE_MODE,
        "match_types": list(MATCH_TYPES),
        "allele_types": list(ALLELE_TYPES),
        "marker_types": list(MARKER_TYPES),
        "ortholog_fields": [{"field": f, "label": label} for f, label in ORTHOLOG_XREF_FIELDS],
        "xref_lookup_sources": sorted(set(XREF_SOURCE_ALIASES.values())),
        "provenance_policy": (
            "Static provenance (citation, MGI release, full research-use notice "
            "text) is declared here and applies to ALL tool outputs; it is not "
            "repeated per-call to conserve context tokens. The research-use "
            "RESTRICTION itself is the exception: per the fleet-wide "
            "Response-Envelope Standard v1, _meta.unsafe_for_clinical_use=true is "
            "stamped on every tool response (success and error, at every "
            "response_mode) so it survives even if this capabilities payload is "
            "never read."
        ),
        "per_call_meta": ["tool", "request_id", "next_commands", "unsafe_for_clinical_use"],
        "id_normalization": (
            "MGI ids accepted/returned as both 'MGI:98968' and '98968'; MP term ids "
            "as 'MP:0005367'."
        ),
        "argument_alias_policy": (
            "argument_aliases are server-side synonyms accepted IN ADDITION to each "
            "tool's canonical parameter (e.g. symbol/marker/mgi_id -> query); an "
            "applied rewrite is disclosed under _meta.argument_aliases_applied. Tool "
            "inputSchemas stay strict, so a schema-validating client should pass the "
            "CANONICAL name shown in tool_signatures; an unknown argument name "
            "returns invalid_input with a did-you-mean."
        ),
        "search_semantics": (
            "search_markers is nomenclature full-text search over marker symbol, "
            "name, and synonyms; exact symbol/synonym hits are pinned first (each "
            "result carries match: exact_symbol|exact_synonym|fts). For "
            "phenotype-driven discovery use search_phenotype_terms then "
            "find_markers_by_phenotype. Resolve an exact symbol/MGI id (or human "
            "ortholog) with resolve_marker."
        ),
        "truncation_contract": (
            "Every list tool (search_markers, get_marker_alleles, "
            "get_marker_phenotypes, find_markers_by_phenotype, "
            "search_phenotype_terms) returns total (matches before the cap), "
            "returned (rows in this payload), limit (cap applied), and truncated "
            "(total > returned). When truncated is true, _meta.next_commands includes "
            "a ready-to-call widen step that raises limit. Never infer completeness "
            "from list length."
        ),
        "response_mode_semantics": {
            "get_marker_phenotypes": (
                "minimal/compact/standard = deduplicated, support-ordered DISTINCT "
                "term list ({mp_id, mp_term, genotype_count}; standard adds "
                "systems[]); full = per-genotype rows with allelic composition, "
                "genetic background, and PubMed. view echoes which shape was returned."
            ),
            "get_marker": (
                "minimal = identity anchors; compact = drops null/verbose "
                "(cm_position/status); standard/full = the complete record."
            ),
            "search_markers/get_marker_alleles": (
                "minimal trims to identity; compact drops null/empty; standard/full "
                "return the full rows."
            ),
        },
        "behavioral_defaults": {
            "find_markers_by_phenotype.include_descendants": (
                "Defaults to true: child (more specific) MP terms are rolled up via "
                "the ontology, so the gene set is broader than exact-term-only. The "
                "flag is echoed in every response."
            ),
            "get_marker_phenotypes.default_view": (
                "compact term view (default limit 250) returns all distinct terms for "
                "a typical gene; pass response_mode=full for per-genotype detail."
            ),
            "resolve_marker.human_symbol_collision": (
                "A human symbol identical (case-insensitively) to the mouse symbol "
                "resolves via the mouse symbol with match_type=current rather than "
                "ortholog; the resolved marker is the same correct mouse marker."
            ),
            "cold_start_fallback": (
                "When the local index is unavailable AND mousemine.enable_live_fallback "
                "is on, resolve_marker and get_marker serve from a live MouseMine query "
                "(genes only; _meta.source='mousemine'; get_marker omits summary counts "
                "and sets _meta.partial). All other tools return data_unavailable while "
                "the index is cold. Default off: behavior is unchanged."
            ),
        },
        "field_glossary": {
            "alleles_total": "get_marker.summary: all phenotypic alleles of the marker.",
            "total_alleles": (
                "get_marker_alleles: all phenotypic alleles (same population as alleles_total)."
            ),
            "phenotyped_alleles": (
                "phenotype summary: distinct alleles appearing in MP annotations (a subset)."
            ),
            "genotype_count": (
                "get_marker_phenotypes term view: distinct genotypes supporting that MP term."
            ),
            "match": "search_markers hit: exact_symbol | exact_synonym | fts.",
        },
        "recommended_workflows": [
            "mouse symbol/MGI id -> resolve_marker -> get_marker -> get_marker_phenotypes",
            "human gene -> resolve_marker (match_type=ortholog) -> get_marker_phenotypes",
            "Mutations & Alleles -> get_marker_alleles (category counts mirror the page)",
            "Phenotype Overview grid -> get_phenotype_overview -> get_marker_phenotypes(mp_system=)",
            "cross-species disease -> get_marker_diseases / get_marker_ortholog",
            "phenotype -> markers -> search_phenotype_terms -> find_markers_by_phenotype(mp_id=)",
        ],
        "not_found_contract": (
            "A symbol/id with no marker returns error_code 'not_found'. An ambiguous "
            "symbol returns 'ambiguous_query' with the candidate list and "
            "next_commands to each candidate."
        ),
        "scope_notes": (
            "Phenotype annotations cover single-locus, NON-conditional genotypes only "
            "(MGI_GenePheno). Conditional/Cre-driven and multi-genic genotypes are "
            "EXCLUDED by this MGI data source and may appear on the MGI gene page (e.g. "
            "tissue-specific renal phenotypes from Cre conditional alleles), so a zero "
            "or partial phenotype result does not mean the gene lacks that phenotype in "
            "mouse. Every phenotype response carries scope='single_locus_genotypes_only' "
            "and a scope_note. IMSR strain availability, gene expression (GXD), and "
            "recombinase activity are also out of scope in v1."
        ),
        "error_codes": [
            "invalid_input",
            "not_found",
            "ambiguous_query",
            "upstream_unavailable",
            "rate_limited",
            "internal",
        ],
        "limits": {
            "max_search_limit": 200,
            "max_allele_limit": 1000,
            "max_phenotype_limit": 1000,
            "max_find_markers_limit": 500,
        },
        "read_only": True,
        "notes": MGI_REFERENCE_NOTES,
    }


async def collect_tool_signatures(mcp: FastMCP) -> dict[str, str]:
    """Map every registered tool to its rendered signature (from the live schema)."""
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    return {t.name: tool_signature(t.name, t.parameters or {}) for t in tools}


async def build_tools_overview(mcp: FastMCP) -> dict[str, Any]:
    """Lightweight discovery payload: name, one-line summary, and call signature."""
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    entries: list[dict[str, str]] = []
    for tool in tools:
        summary = (tool.description or "").split(". ")[0].strip()
        entries.append(
            {
                "name": tool.name,
                "summary": summary[:160],
                "signature": tool_signature(tool.name, tool.parameters or {}),
            }
        )
    return {"server": "mgi-link", "tool_count": len(entries), "tools": entries}


def project_capabilities(detail: str, tool_signatures: dict[str, str]) -> dict[str, Any]:
    """Return the full capabilities payload, or a light summary (default)."""
    full = build_capabilities()
    full["tool_signatures"] = tool_signatures
    full["argument_aliases"] = _ALIAS_DOC
    if detail == "full":
        full["detail"] = "full"
        return full
    summary: dict[str, Any] = {k: full[k] for k in _SUMMARY_KEYS if k in full}
    summary["tool_signatures"] = tool_signatures
    summary["argument_aliases"] = _ALIAS_DOC
    summary["detail"] = "summary"
    summary["more"] = (
        "Call get_server_capabilities(detail='full') or read mgi://capabilities "
        "for vocabularies (allele/marker types, ortholog fields); mgi://tools lists signatures."
    )
    return summary


def register_capability_resources(mcp: FastMCP) -> None:
    """Register the mgi:// resource family on a FastMCP instance."""

    @mcp.resource("mgi://capabilities", mime_type="application/json")
    def capabilities() -> str:
        return json.dumps(build_capabilities(), indent=2)

    @mcp.resource("mgi://tools", mime_type="application/json")
    async def tools_overview() -> str:
        return json.dumps(await build_tools_overview(mcp), indent=2)

    @mcp.resource("mgi://usage", mime_type="text/plain")
    def usage() -> str:
        return MGI_USAGE_NOTES

    @mcp.resource("mgi://reference", mime_type="text/plain")
    def reference() -> str:
        return MGI_REFERENCE_NOTES

    @mcp.resource("mgi://research-use", mime_type="text/plain")
    def research_use() -> str:
        return RESEARCH_USE_NOTICE

    @mcp.resource("mgi://citation", mime_type="text/plain")
    def citation() -> str:
        return RECOMMENDED_CITATION
