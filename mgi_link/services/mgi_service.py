"""Orchestration over the read-only repository.

Returns plain dicts (no envelope); the MCP layer owns ``success``/``_meta``.
The resolution cascade (MGI id -> current symbol -> synonym -> human ortholog)
returns the match provenance and surfaces ambiguity instead of silently
collapsing it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mgi_link.constants import (
    ALLELE_TYPE_ALIASES,
    ORTHOLOG_XREF_FIELDS,
    XREF_SOURCE_ALIASES,
)
from mgi_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    InvalidInputError,
    NotFoundError,
)
from mgi_link.identifiers import (
    infer_xref_source,
    looks_like_mgi_id,
    normalize_mgi_id,
    normalize_mp_id,
)
from mgi_link.services.pagination import page_fields
from mgi_link.services.shaping import (
    shape_allele,
    shape_marker,
    shape_phenotype_genotype,
    shape_phenotype_term,
    shape_resolution,
    shape_summary,
)

if TYPE_CHECKING:
    from mgi_link.data.repository import MgiRepository

_MAX_CANDIDATES = 25


class MgiService:
    """High-level MGI operations backed by the local SQLite index."""

    def __init__(self, repository: MgiRepository | None) -> None:
        """Wire a repository (primary data source)."""
        self._repo = repository

    @property
    def repo(self) -> MgiRepository:
        """Return the repository or raise a data-unavailable error."""
        if self._repo is None:
            raise DataUnavailableError(
                "The local MGI index is not built yet. Run `mgi-link-data build`."
            )
        return self._repo

    # -- diagnostics -----------------------------------------------------------

    def get_diagnostics(self) -> dict[str, Any]:
        """Return data-source provenance and freshness."""
        if self._repo is None:
            return {
                "data_available": False,
                "message": "Local MGI index not built. Run `mgi-link-data build`.",
            }
        meta = self._repo.get_meta()
        return {
            "data_available": True,
            "release": meta.get("release"),
            "marker_count": meta.get("marker_count"),
            "allele_count": meta.get("allele_count"),
            "genopheno_count": meta.get("genopheno_count"),
            "mp_term_count": meta.get("mp_term_count"),
            "ortholog_count": meta.get("ortholog_count"),
            "disease_count": meta.get("disease_count"),
            "schema_version": meta.get("schema_version"),
            "built_utc": meta.get("build_utc"),
        }

    # -- resolution ------------------------------------------------------------

    def _resolve_to_marker(self, raw: str) -> tuple[dict[str, Any], str]:
        """Resolve any id/symbol/ortholog to ``(marker, match_type)`` or raise."""
        mgi_id = normalize_mgi_id(raw)
        if mgi_id:
            marker = self.repo.get_marker(mgi_id)
            if marker is not None:
                return marker, "mgi_id"
            raise NotFoundError(f"No MGI marker for {mgi_id}.")

        pairs = self.repo.lookup_symbol(raw)
        if pairs:
            best_type = pairs[0][1]
            best = [p for p in pairs if p[1] == best_type]
            if len(best) > 1:
                raise self._ambiguity_error(raw, best_type, best)
            marker = self.repo.get_marker(best[0][0])
            if marker is not None:
                return marker, best_type

        ortholog_id = self._resolve_via_xref(raw)
        if ortholog_id is not None:
            marker = self.repo.get_marker(ortholog_id)
            if marker is not None:
                return marker, "ortholog"

        raise NotFoundError(
            f"No MGI marker matches '{raw}'. Try an MGI id, a mouse symbol, or a "
            "human gene symbol/HGNC id for the ortholog."
        )

    def _resolve_via_xref(self, raw: str) -> str | None:
        """Try the xref index (human symbol, HGNC, Ensembl) for a marker id."""
        candidates: list[str] = []
        source = infer_xref_source(raw)
        if source:
            candidates.append(source)
        # A bare word might be a human gene symbol.
        if not looks_like_mgi_id(raw):
            candidates.append("human_symbol")
        for src in candidates:
            ids = self.repo.lookup_by_xref(src, raw)
            if ids:
                return ids[0]
        return None

    def _ambiguity_error(
        self, raw: str, best_type: str, best: list[tuple[str, str]]
    ) -> AmbiguousQueryError:
        candidates = [
            _brief(self.repo.get_marker(mid) or {"mgi_id": mid}, stype) for mid, stype in best
        ]
        return AmbiguousQueryError(
            f"'{raw}' is a {best_type} symbol for {len(best)} markers; pick one and call get_marker.",
            candidates=candidates,
        )

    def resolve(self, query: str, mode: str = "compact") -> dict[str, Any]:
        """Resolve any id/symbol/ortholog to a canonical marker (provenance)."""
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError("query must be a non-empty symbol or MGI id.", field="query")
        marker, match_type = self._resolve_to_marker(raw)
        record = {
            "query": raw,
            "mgi_id": marker.get("mgi_id"),
            "symbol": marker.get("symbol"),
            "name": marker.get("name"),
            "marker_type": marker.get("marker_type"),
            "feature_type": marker.get("feature_type"),
            "location": _location(marker),
            "match_type": match_type,
        }
        return shape_resolution(record, mode)

    # -- marker record ---------------------------------------------------------

    def get_marker(self, query: str, mode: str = "compact") -> dict[str, Any]:
        """Return the full marker record + ortholog + summary counts."""
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError("query must be a non-empty symbol or MGI id.", field="query")
        marker, match_type = self._resolve_to_marker(raw)
        mgi_id = marker["mgi_id"]
        record = dict(marker)
        record["requested_query"] = raw
        record["match_type"] = match_type
        record["location"] = _location(marker)
        ortholog = self.repo.get_ortholog(mgi_id)
        if ortholog:
            record["human_ortholog"] = {
                "symbol": ortholog.get("human_symbol"),
                "hgnc_id": ortholog.get("hgnc_id"),
                "omim_gene_id": ortholog.get("omim_gene_id"),
            }
        counts = self.repo.allele_category_counts(mgi_id)
        pheno = self.repo.phenotype_summary(mgi_id)
        record["summary"] = {
            "alleles_total": sum(counts.values()),
            "phenotypes": pheno["phenotypes"],
            "phenotype_references": pheno["references"],
            "diseases": len(self.repo.get_diseases(mgi_id)),
        }
        return shape_marker(record, mode)

    def search(
        self, query: str, *, marker_type: str | None = None, limit: int = 25, mode: str = "compact"
    ) -> dict[str, Any]:
        """Free-text search over marker symbol/name/synonyms."""
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError("query must be a non-empty search string.", field="query")
        limit = max(1, min(limit, 200))
        hits = self.repo.search(raw, limit=limit, marker_type=marker_type)
        total = self.repo.count_search(raw, marker_type=marker_type)
        results = [shape_summary(h, mode) for h in hits]
        return {
            "query": raw,
            "marker_type": marker_type,
            **page_fields(total=total, returned=len(results), limit=limit),
            "results": results,
        }

    # -- alleles ---------------------------------------------------------------

    def get_alleles(
        self,
        query: str,
        *,
        allele_type: str | None = None,
        limit: int = 200,
        mode: str = "compact",
    ) -> dict[str, Any]:
        """Return alleles + generation-method category counts for a marker."""
        marker, _ = self._resolve_to_marker((query or "").strip())
        mgi_id = marker["mgi_id"]
        limit = max(1, min(limit, 1000))
        type_filter = _normalize_allele_type(allele_type)
        category_counts = self.repo.allele_category_counts(mgi_id)
        alleles = self.repo.get_alleles(mgi_id, allele_type=type_filter, limit=limit)
        if type_filter:
            total = sum(n for t, n in category_counts.items() if type_filter.lower() in t.lower())
        else:
            total = sum(category_counts.values())
        shaped = [shape_allele(a, mode) for a in alleles]
        return {
            "mgi_id": mgi_id,
            "symbol": marker.get("symbol"),
            "allele_type_filter": type_filter,
            "total_alleles": total,
            "category_counts": category_counts,
            **page_fields(total=total, returned=len(shaped), limit=limit),
            "alleles": shaped,
        }

    # -- phenotypes ------------------------------------------------------------

    def get_phenotypes(
        self,
        query: str,
        *,
        mp_system: str | None = None,
        limit: int = 250,
        mode: str = "compact",
    ) -> dict[str, Any]:
        """Return MP annotations + phenotype summary for a marker.

        minimal/compact/standard return a deduplicated, support-ordered DISTINCT
        TERM view; full returns the per-genotype rows. ``limit`` applies to the unit
        each view emits and the truncation contract makes any cap explicit.
        """
        marker, _ = self._resolve_to_marker((query or "").strip())
        mgi_id = marker["mgi_id"]
        limit = max(1, min(limit, 1000))
        system_id = self._resolve_system(mp_system) if mp_system else None
        summary = self.repo.phenotype_summary(mgi_id)
        if mode == "full":
            total = self.repo.count_phenotype_rows(mgi_id, system_id=system_id)
            rows = self.repo.get_phenotypes(mgi_id, system_id=system_id, limit=limit)
            annotations = [shape_phenotype_genotype(r) for r in rows]
            view = "per_genotype"
        else:
            total = self.repo.count_phenotype_terms(mgi_id, system_id=system_id)
            term_rows = self.repo.phenotype_terms(mgi_id, system_id=system_id, limit=limit)
            annotations = [shape_phenotype_term(r, mode) for r in term_rows]
            view = "terms"
        return {
            "mgi_id": mgi_id,
            "symbol": marker.get("symbol"),
            "mp_system_filter": system_id,
            "view": view,
            "summary": summary,
            **page_fields(total=total, returned=len(annotations), limit=limit),
            "annotations": annotations,
        }

    def get_phenotype_overview(self, query: str) -> dict[str, Any]:
        """Return the top-level MP system grid (Phenotype Overview) for a marker."""
        marker, _ = self._resolve_to_marker((query or "").strip())
        mgi_id = marker["mgi_id"]
        overview = self.repo.phenotype_overview(mgi_id)
        summary = self.repo.phenotype_summary(mgi_id)
        return {
            "mgi_id": mgi_id,
            "symbol": marker.get("symbol"),
            "summary": summary,
            "system_count": len(overview),
            "systems": overview,
        }

    # -- diseases & orthologs --------------------------------------------------

    def get_diseases(self, query: str) -> dict[str, Any]:
        """Return human-mouse disease models for a marker."""
        marker, _ = self._resolve_to_marker((query or "").strip())
        mgi_id = marker["mgi_id"]
        diseases = self.repo.get_diseases(mgi_id)
        return {
            "mgi_id": mgi_id,
            "symbol": marker.get("symbol"),
            "count": len(diseases),
            "diseases": diseases,
        }

    def get_ortholog(self, query: str, mode: str = "compact") -> dict[str, Any]:
        """Return the mouse<->human ortholog mapping for a marker (or human gene)."""
        marker, match_type = self._resolve_to_marker((query or "").strip())
        mgi_id = marker["mgi_id"]
        ortholog = self.repo.get_ortholog(mgi_id)
        xrefs: dict[str, Any] = {}
        if ortholog:
            for field, label in ORTHOLOG_XREF_FIELDS:
                value = ortholog.get(field)
                if value:
                    xrefs[field] = {"database": label, "value": value}
        return {
            "mgi_id": mgi_id,
            "mouse_symbol": marker.get("symbol"),
            "match_type": match_type,
            "has_ortholog": bool(ortholog and ortholog.get("human_symbol")),
            "ortholog": xrefs,
        }

    # -- ontology --------------------------------------------------------------

    def get_mp_term(self, mp_id: str) -> dict[str, Any]:
        """Return an MP ontology term (id, name, definition, parents, children)."""
        normalized = normalize_mp_id((mp_id or "").strip())
        if not normalized:
            raise InvalidInputError("mp_id must be an MP term id like MP:0005367.", field="mp_id")
        term = self.repo.get_mp_term(normalized)
        if term is None:
            raise NotFoundError(f"No MP term {normalized}.")
        return term

    def search_phenotype_terms(self, query: str, *, limit: int = 25) -> dict[str, Any]:
        """FTS over MP term names/definitions."""
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError("query must be a non-empty search string.", field="query")
        limit = max(1, min(limit, 200))
        hits = self.repo.search_mp(raw, limit=limit)
        total = self.repo.count_mp(raw)
        return {
            "query": raw,
            **page_fields(total=total, returned=len(hits), limit=limit),
            "results": hits,
        }

    def find_markers_by_phenotype(
        self, mp_id: str, *, include_descendants: bool = True, limit: int = 100
    ) -> dict[str, Any]:
        """Reverse lookup: MP term -> mouse markers annotated with it."""
        normalized = normalize_mp_id((mp_id or "").strip())
        if not normalized:
            raise InvalidInputError("mp_id must be an MP term id like MP:0005367.", field="mp_id")
        term = self.repo.get_mp_term(normalized)
        if term is None:
            raise NotFoundError(f"No MP term {normalized}.")
        limit = max(1, min(limit, 500))
        markers = self.repo.markers_by_phenotype(
            normalized, include_descendants=include_descendants, limit=limit
        )
        total = self.repo.count_markers_by_phenotype(
            normalized, include_descendants=include_descendants
        )
        return {
            "mp_id": normalized,
            "mp_term": term["name"],
            "include_descendants": include_descendants,
            **page_fields(total=total, returned=len(markers), limit=limit),
            "markers": markers,
        }

    def _resolve_system(self, mp_system: str) -> str:
        """Resolve a system filter (MP id or name) to a top-level MP id."""
        raw = mp_system.strip()
        normalized = normalize_mp_id(raw)
        systems = self.repo.top_systems()
        if normalized:
            if any(s["mp_id"] == normalized for s in systems):
                return normalized
            raise InvalidInputError(
                f"{normalized} is not a top-level MP system.",
                field="mp_system",
                allowed=[s["name"] for s in systems],
            )
        low = raw.lower()
        for s in systems:
            if s["name"].lower() == low or low in s["name"].lower():
                return s["mp_id"]
        raise InvalidInputError(
            f"Unknown MP system '{mp_system}'.",
            field="mp_system",
            allowed=[s["name"] for s in systems],
            hint="Use a top-level system name (e.g. 'renal/urinary system') or its MP id.",
        )


def _normalize_allele_type(allele_type: str | None) -> str | None:
    """Map a friendly allele-type token to a canonical substring, or pass through."""
    if not allele_type:
        return None
    return ALLELE_TYPE_ALIASES.get(allele_type.strip().lower(), allele_type.strip())


def _location(marker: dict[str, Any]) -> str | None:
    """Build a human-readable location string from a marker record."""
    chrom = marker.get("chromosome")
    start = marker.get("coord_start")
    end = marker.get("coord_end")
    strand = marker.get("strand") or ""
    if chrom and start and end:
        return f"Chr{chrom}:{start}-{end}{strand} (GRCm39)"
    if chrom:
        return f"Chr{chrom}"
    return None


def _brief(marker: dict[str, Any], symbol_type: str) -> dict[str, Any]:
    """Compact candidate/summary view of a marker."""
    return {
        "mgi_id": marker.get("mgi_id"),
        "symbol": marker.get("symbol"),
        "name": marker.get("name"),
        "marker_type": marker.get("marker_type"),
        "symbol_type": symbol_type,
    }


# Re-export for xref source validation in tools.
XREF_SOURCES = sorted(set(XREF_SOURCE_ALIASES.values()))
