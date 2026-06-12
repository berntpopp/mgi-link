"""Read-only SQLite repository for the built MGI index.

All indexes are pre-computed by the builder, so this layer only reads rows and
decodes the JSON list columns. FTS5 queries are sanitized so raw user text never
reaches ``MATCH`` (which can raise on operator characters), with a ``LIKE``
fallback for pathological input.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from mgi_link.data.repository_ontology import MpOntologyMixin
from mgi_link.exceptions import DataUnavailableError

_TYPE_PRIORITY = {"current": 0, "synonym": 1}


class MgiRepository(MpOntologyMixin):
    """Read-only access to the built MGI SQLite index."""

    def __init__(self, db_path: Path | str) -> None:
        """Open a read-only connection to the MGI database."""
        self._path = Path(db_path)
        if not self._path.exists():
            raise DataUnavailableError(
                f"MGI database not found at {self._path}. Build it with `mgi-link-data build`."
            )
        try:
            self._conn = sqlite3.connect(
                f"file:{self._path}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.Error as exc:  # pragma: no cover - rare OS-level failure
            raise DataUnavailableError(f"Cannot open MGI database at {self._path}: {exc}.") from exc
        self._conn.row_factory = sqlite3.Row

    # -- provenance ------------------------------------------------------------

    def get_meta(self) -> dict[str, Any]:
        """Return build provenance from the ``meta`` table."""
        try:
            row = self._conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            raise DataUnavailableError(
                f"MGI database at {self._path} is unreadable: {exc}."
            ) from exc
        if row is None:
            raise DataUnavailableError(f"MGI database at {self._path} has no build metadata.")
        return dict(row)

    # -- marker records --------------------------------------------------------

    @staticmethod
    def _marker_from_row(row: sqlite3.Row) -> dict[str, Any]:
        record: dict[str, Any] = {}
        for key in row.keys():  # noqa: SIM118
            if key == "symbol_upper":
                continue
            value = row[key]
            record[key] = json.loads(value) if key == "synonyms" and value else value
        if "synonyms" in record and not record["synonyms"]:
            record["synonyms"] = []
        return record

    def get_marker(self, mgi_id: str) -> dict[str, Any] | None:
        """Return the full marker record for an MGI id, or ``None``."""
        row = self._conn.execute("SELECT * FROM marker WHERE mgi_id = ?", (mgi_id,)).fetchone()
        return self._marker_from_row(row) if row is not None else None

    def get_marker_by_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Return the marker whose symbol matches (case-insensitive)."""
        row = self._conn.execute(
            "SELECT * FROM marker WHERE symbol_upper = ?", (symbol.upper(),)
        ).fetchone()
        return self._marker_from_row(row) if row is not None else None

    # -- resolution ------------------------------------------------------------

    def lookup_symbol(self, symbol: str) -> list[tuple[str, str]]:
        """Return ``(mgi_id, symbol_type)`` rows for a symbol, best type first."""
        rows = self._conn.execute(
            "SELECT mgi_id, symbol_type FROM marker_lookup WHERE lookup_symbol = ?",
            (symbol.upper(),),
        ).fetchall()
        pairs = [(r["mgi_id"], r["symbol_type"]) for r in rows]
        pairs.sort(key=lambda p: _TYPE_PRIORITY.get(p[1], 9))
        return pairs

    def lookup_by_xref(self, source: str, value: str) -> list[str]:
        """Return MGI ids whose ``source`` cross-reference equals ``value``."""
        rows = self._conn.execute(
            "SELECT DISTINCT mgi_id FROM xref WHERE source = ? AND value_upper = ?",
            (source, value.strip().upper()),
        ).fetchall()
        return [r["mgi_id"] for r in rows]

    # -- search ----------------------------------------------------------------

    def search(
        self, query: str, *, limit: int, marker_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Exact symbol/synonym hits pinned first, then FTS relevance."""
        q_upper = query.strip().upper()
        exact_sql = (
            "SELECT m.mgi_id, m.symbol, m.name, m.marker_type, m.feature_type, "
            "m.chromosome, ml.symbol_type FROM marker_lookup ml "
            "JOIN marker m ON m.mgi_id = ml.mgi_id WHERE ml.lookup_symbol = ?"
        )
        eparams: list[Any] = [q_upper]
        if marker_type:
            exact_sql += " AND m.marker_type = ?"
            eparams.append(marker_type)
        exact_sql += " ORDER BY CASE ml.symbol_type WHEN 'current' THEN 0 ELSE 1 END"
        exact_rows = self._conn.execute(exact_sql, tuple(eparams)).fetchall()

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for r in exact_rows:
            if r["mgi_id"] in seen:
                continue
            seen.add(r["mgi_id"])
            summary = self._summary_from_row(r)
            summary["match"] = "exact_symbol" if r["symbol_type"] == "current" else "exact_synonym"
            results.append(summary)

        if len(results) < limit:
            for r in self._fts_rows(query, limit=limit + len(results), marker_type=marker_type):
                if r["mgi_id"] in seen:
                    continue
                seen.add(r["mgi_id"])
                summary = self._summary_from_row(r)
                summary["match"] = "fts"
                results.append(summary)
                if len(results) >= limit:
                    break
        return results[:limit]

    def _fts_rows(self, query: str, *, limit: int, marker_type: str | None) -> list[sqlite3.Row]:
        """Raw FTS rows (with LIKE fallback) — used by search()."""
        match = self._fts_query(query)
        sql = (
            "SELECT m.mgi_id, m.symbol, m.name, m.marker_type, m.feature_type, "
            "m.chromosome, bm25(marker_fts) AS rank "
            "FROM marker_fts JOIN marker m ON m.mgi_id = marker_fts.mgi_id "
            "WHERE marker_fts MATCH ?"
        )
        params: list[Any] = [match]
        if marker_type:
            sql += " AND m.marker_type = ?"
            params.append(marker_type)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            return self._conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error:
            return self._search_like(query, limit=limit, marker_type=marker_type)

    def count_search(self, query: str, *, marker_type: str | None = None) -> int:
        """Total markers matching the FTS query (before any limit)."""
        match = self._fts_query(query)
        sql = (
            "SELECT COUNT(*) AS n FROM marker_fts "
            "JOIN marker m ON m.mgi_id = marker_fts.mgi_id WHERE marker_fts MATCH ?"
        )
        params: list[Any] = [match]
        if marker_type:
            sql += " AND m.marker_type = ?"
            params.append(marker_type)
        try:
            return int(self._conn.execute(sql, tuple(params)).fetchone()["n"])
        except sqlite3.Error:
            pattern = "%" + query.upper().replace("%", "").replace("_", "") + "%"
            like = (
                "SELECT COUNT(*) AS n FROM marker WHERE (symbol_upper LIKE ? OR UPPER(name) LIKE ?)"
            )
            lparams: list[Any] = [pattern, pattern]
            if marker_type:
                like += " AND marker_type = ?"
                lparams.append(marker_type)
            return int(self._conn.execute(like, tuple(lparams)).fetchone()["n"])

    def _search_like(self, query: str, *, limit: int, marker_type: str | None) -> list[sqlite3.Row]:
        pattern = "%" + query.upper().replace("%", "").replace("_", "") + "%"
        sql = (
            "SELECT mgi_id, symbol, name, marker_type, feature_type, chromosome, "
            "0.0 AS rank FROM marker WHERE (symbol_upper LIKE ? OR UPPER(name) LIKE ?)"
        )
        params: list[Any] = [pattern, pattern]
        if marker_type:
            sql += " AND marker_type = ?"
            params.append(marker_type)
        sql += " ORDER BY symbol LIMIT ?"
        params.append(limit)
        return self._conn.execute(sql, tuple(params)).fetchall()

    @staticmethod
    def _summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
        rank = row["rank"] if "rank" in row.keys() else 0.0  # noqa: SIM118
        return {
            "mgi_id": row["mgi_id"],
            "symbol": row["symbol"],
            "name": row["name"],
            "marker_type": row["marker_type"],
            "feature_type": row["feature_type"],
            "chromosome": row["chromosome"],
            "score": round(-rank, 4) if rank else 0.0,
        }

    # -- alleles ---------------------------------------------------------------

    def get_alleles(
        self, marker_id: str, *, allele_type: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return alleles for a marker (optionally filtered by type substring)."""
        sql = "SELECT * FROM allele WHERE marker_id = ?"
        params: list[Any] = [marker_id]
        if allele_type:
            sql += " AND allele_type LIKE ?"
            params.append(f"%{allele_type}%")
        sql += " ORDER BY symbol"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [self._allele_from_row(r) for r in rows]

    @staticmethod
    def _allele_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "allele_id": row["allele_id"],
            "symbol": row["symbol"],
            "name": row["name"],
            "allele_type": row["allele_type"],
            "attributes": json.loads(row["attributes"]) if row["attributes"] else [],
            "pubmed_ids": json.loads(row["pubmed_ids"]) if row["pubmed_ids"] else [],
            "marker_id": row["marker_id"],
            "marker_symbol": row["marker_symbol"],
        }

    def allele_category_counts(self, marker_id: str) -> dict[str, int]:
        """Return ``{allele_type: count}`` for a marker, plus the total."""
        rows = self._conn.execute(
            "SELECT COALESCE(allele_type, 'Unspecified') AS t, COUNT(*) AS n "
            "FROM allele WHERE marker_id = ? GROUP BY allele_type ORDER BY n DESC",
            (marker_id,),
        ).fetchall()
        return {r["t"]: r["n"] for r in rows}

    # -- phenotypes ------------------------------------------------------------

    def get_phenotypes(
        self, marker_id: str, *, system_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return gene->phenotype annotation rows for a marker, joined to MP names."""
        sql = (
            "SELECT gp.mp_id, t.name AS mp_term, gp.allelic_composition, gp.allele_symbols, "
            "gp.allele_ids, gp.genetic_background, gp.pubmed_id, gp.genotype_id "
            "FROM genopheno gp LEFT JOIN mp_term t ON t.mp_id = gp.mp_id WHERE gp.marker_id = ?"
        )
        params: list[Any] = [marker_id]
        if system_id:
            sql += " AND gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            params.append(system_id)
        sql += " ORDER BY t.name"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "mp_id": r["mp_id"],
                "mp_term": r["mp_term"],
                "allelic_composition": r["allelic_composition"],
                "allele_symbols": r["allele_symbols"],
                "allele_ids": json.loads(r["allele_ids"]) if r["allele_ids"] else [],
                "genetic_background": r["genetic_background"],
                "pubmed_id": r["pubmed_id"],
                "genotype_id": r["genotype_id"],
            }
            for r in rows
        ]

    def phenotype_terms(
        self, marker_id: str, *, system_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Distinct MP terms for a marker with genotype support, support-ordered."""
        sql = (
            "SELECT gp.mp_id, t.name AS mp_term, "
            "COUNT(DISTINCT gp.genotype_id) AS genotype_count, "
            "(SELECT group_concat(DISTINCT s.name) FROM mp_top_system s "
            " JOIN mp_closure c ON c.ancestor_id = s.mp_id WHERE c.mp_id = gp.mp_id) AS systems "
            "FROM genopheno gp LEFT JOIN mp_term t ON t.mp_id = gp.mp_id "
            "WHERE gp.marker_id = ?"
        )
        params: list[Any] = [marker_id]
        if system_id:
            sql += " AND gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            params.append(system_id)
        sql += " GROUP BY gp.mp_id, t.name ORDER BY genotype_count DESC, t.name"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "mp_id": r["mp_id"],
                "mp_term": r["mp_term"],
                "genotype_count": r["genotype_count"],
                "systems": r["systems"].split(",") if r["systems"] else [],
            }
            for r in rows
        ]

    def count_phenotype_terms(self, marker_id: str, *, system_id: str | None = None) -> int:
        """Distinct MP-term count for a marker (term-view total)."""
        sql = "SELECT COUNT(DISTINCT gp.mp_id) AS n FROM genopheno gp WHERE gp.marker_id = ?"
        params: list[Any] = [marker_id]
        if system_id:
            sql += " AND gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            params.append(system_id)
        return int(self._conn.execute(sql, tuple(params)).fetchone()["n"])

    def count_phenotype_rows(self, marker_id: str, *, system_id: str | None = None) -> int:
        """Per-genotype annotation-row count for a marker (full-view total)."""
        sql = "SELECT COUNT(*) AS n FROM genopheno gp WHERE gp.marker_id = ?"
        params: list[Any] = [marker_id]
        if system_id:
            sql += " AND gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            params.append(system_id)
        return int(self._conn.execute(sql, tuple(params)).fetchone()["n"])

    def phenotype_summary(self, marker_id: str) -> dict[str, int]:
        """Return phenotype-summary counts for a marker (the page header line)."""
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT mp_id) AS phenotypes, "
            "COUNT(DISTINCT genetic_background) AS backgrounds, "
            "COUNT(DISTINCT genotype_id) AS genotypes, "
            "COUNT(DISTINCT pubmed_id) AS references_ "
            "FROM genopheno WHERE marker_id = ?",
            (marker_id,),
        ).fetchone()
        allele_rows = self._conn.execute(
            "SELECT allele_ids FROM genopheno WHERE marker_id = ?", (marker_id,)
        ).fetchall()
        alleles: set[str] = set()
        for r in allele_rows:
            if r["allele_ids"]:
                alleles.update(json.loads(r["allele_ids"]))
        return {
            "phenotypes": row["phenotypes"] or 0,
            "phenotyped_alleles": len(alleles),
            "genetic_backgrounds": row["backgrounds"] or 0,
            "genotypes": row["genotypes"] or 0,
            "references": row["references_"] or 0,
        }

    def phenotype_overview(self, marker_id: str) -> list[dict[str, Any]]:
        """Return per top-level MP system the distinct annotated terms for a marker."""
        rows = self._conn.execute(
            "SELECT s.mp_id AS system_id, s.name AS system_name, s.display_order, "
            "gp.mp_id AS mp_id, t.name AS mp_term "
            "FROM mp_top_system s "
            "JOIN mp_closure c ON c.ancestor_id = s.mp_id "
            "JOIN genopheno gp ON gp.mp_id = c.mp_id AND gp.marker_id = ? "
            "LEFT JOIN mp_term t ON t.mp_id = gp.mp_id "
            "ORDER BY s.display_order, t.name",
            (marker_id,),
        ).fetchall()
        systems: dict[str, dict[str, Any]] = {}
        for r in rows:
            sys = systems.setdefault(
                r["system_id"],
                {"system_id": r["system_id"], "system": r["system_name"], "terms": []},
            )
            entry = {"mp_id": r["mp_id"], "term": r["mp_term"]}
            if entry not in sys["terms"]:
                sys["terms"].append(entry)
        for sys in systems.values():
            sys["count"] = len(sys["terms"])
        return list(systems.values())

    def markers_by_phenotype(
        self, mp_id: str, *, include_descendants: bool, limit: int
    ) -> list[dict[str, Any]]:
        """Return markers annotated with an MP term (optionally incl. descendants)."""
        if include_descendants:
            sql = (
                "SELECT DISTINCT gp.marker_id, m.symbol, m.name, m.marker_type "
                "FROM genopheno gp JOIN marker m ON m.mgi_id = gp.marker_id "
                "WHERE gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?) "
                "ORDER BY m.symbol LIMIT ?"
            )
        else:
            sql = (
                "SELECT DISTINCT gp.marker_id, m.symbol, m.name, m.marker_type "
                "FROM genopheno gp JOIN marker m ON m.mgi_id = gp.marker_id "
                "WHERE gp.mp_id = ? ORDER BY m.symbol LIMIT ?"
            )
        rows = self._conn.execute(sql, (mp_id, limit)).fetchall()
        return [
            {
                "mgi_id": r["marker_id"],
                "symbol": r["symbol"],
                "name": r["name"],
                "marker_type": r["marker_type"],
            }
            for r in rows
        ]

    def count_markers_by_phenotype(self, mp_id: str, *, include_descendants: bool) -> int:
        """Total distinct markers annotated with an MP term (reverse-lookup total)."""
        if include_descendants:
            sql = (
                "SELECT COUNT(DISTINCT gp.marker_id) AS n FROM genopheno gp "
                "WHERE gp.mp_id IN (SELECT mp_id FROM mp_closure WHERE ancestor_id = ?)"
            )
        else:
            sql = "SELECT COUNT(DISTINCT gp.marker_id) AS n FROM genopheno gp WHERE gp.mp_id = ?"
        return int(self._conn.execute(sql, (mp_id,)).fetchone()["n"])

    # -- orthologs & diseases --------------------------------------------------

    def get_ortholog(self, mgi_id: str) -> dict[str, Any] | None:
        """Return the mouse->human ortholog record for an MGI id, or ``None``."""
        row = self._conn.execute("SELECT * FROM ortholog WHERE mgi_id = ?", (mgi_id,)).fetchone()
        return dict(row) if row is not None else None

    def get_diseases(self, marker_id: str) -> list[dict[str, Any]]:
        """Return human-mouse disease models for a marker."""
        rows = self._conn.execute(
            "SELECT doid, disease_name, omim_ids FROM disease_model WHERE marker_id = ? "
            "ORDER BY disease_name",
            (marker_id,),
        ).fetchall()
        return [
            {
                "doid": r["doid"],
                "disease_name": r["disease_name"],
                "omim_ids": json.loads(r["omim_ids"]) if r["omim_ids"] else [],
            }
            for r in rows
        ]

    def close(self) -> None:
        """Release the underlying database connection."""
        self._conn.close()
