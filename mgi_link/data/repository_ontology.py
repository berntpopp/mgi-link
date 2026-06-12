"""MP-ontology read methods, mixed into :class:`MgiRepository`.

Split out of ``repository.py`` to keep each file within the per-file line budget.
The mixin reads the same read-only connection (``self._conn``) and owns the shared
FTS5 query sanitiser used by both marker and MP search.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class MpOntologyMixin:
    """Read methods over the MP vocabulary, closure, and top-system tables."""

    _conn: sqlite3.Connection

    @staticmethod
    def _fts_query(text: str) -> str:
        """Build a safe FTS5 MATCH string (token OR, last token prefix-matched)."""
        tokens = _FTS_TOKEN_RE.findall(text or "")
        if not tokens:
            return '""'
        quoted = [f'"{tok}"' for tok in tokens[:-1]]
        quoted.append(f'"{tokens[-1]}"*')
        return " OR ".join(quoted)

    def get_mp_term(self, mp_id: str) -> dict[str, Any] | None:
        """Return an MP term with its direct parents/children + top systems."""
        row = self._conn.execute("SELECT * FROM mp_term WHERE mp_id = ?", (mp_id,)).fetchone()
        if row is None:
            return None
        parents = self._conn.execute(
            "SELECT p.parent_id AS id, t.name FROM mp_parent p "
            "LEFT JOIN mp_term t ON t.mp_id = p.parent_id WHERE p.mp_id = ? ORDER BY t.name",
            (mp_id,),
        ).fetchall()
        children = self._conn.execute(
            "SELECT p.mp_id AS id, t.name FROM mp_parent p "
            "LEFT JOIN mp_term t ON t.mp_id = p.mp_id WHERE p.parent_id = ? ORDER BY t.name",
            (mp_id,),
        ).fetchall()
        systems = self._conn.execute(
            "SELECT s.mp_id AS id, s.name FROM mp_top_system s "
            "JOIN mp_closure c ON c.ancestor_id = s.mp_id WHERE c.mp_id = ? ORDER BY s.name",
            (mp_id,),
        ).fetchall()
        return {
            "mp_id": row["mp_id"],
            "name": row["name"],
            "definition": row["definition"],
            "parents": [{"mp_id": r["id"], "name": r["name"]} for r in parents],
            "children": [{"mp_id": r["id"], "name": r["name"]} for r in children],
            "top_level_systems": [{"mp_id": r["id"], "name": r["name"]} for r in systems],
        }

    def search_mp(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        """FTS over MP term name/definition."""
        match = self._fts_query(query)
        try:
            rows = self._conn.execute(
                "SELECT t.mp_id, t.name, t.definition, bm25(mp_fts) AS rank "
                "FROM mp_fts JOIN mp_term t ON t.mp_id = mp_fts.mp_id "
                "WHERE mp_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, limit),
            ).fetchall()
        except sqlite3.Error:
            pattern = "%" + query.upper().replace("%", "").replace("_", "") + "%"
            rows = self._conn.execute(
                "SELECT mp_id, name, definition, 0.0 AS rank FROM mp_term "
                "WHERE UPPER(name) LIKE ? ORDER BY name LIMIT ?",
                (pattern, limit),
            ).fetchall()
        return [
            {
                "mp_id": r["mp_id"],
                "name": r["name"],
                "definition": r["definition"],
                "score": round(-r["rank"], 4) if r["rank"] else 0.0,
            }
            for r in rows
        ]

    def count_mp(self, query: str) -> int:
        """Total MP terms matching the FTS query (before any limit)."""
        match = self._fts_query(query)
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM mp_fts WHERE mp_fts MATCH ?", (match,)
            ).fetchone()
            return int(row["n"])
        except sqlite3.Error:
            pattern = "%" + query.upper().replace("%", "").replace("_", "") + "%"
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM mp_term WHERE UPPER(name) LIKE ?", (pattern,)
            ).fetchone()
            return int(row["n"])

    def top_systems(self) -> list[dict[str, str]]:
        """Return the top-level MP systems (Phenotype Overview grid columns)."""
        rows = self._conn.execute(
            "SELECT mp_id, name FROM mp_top_system ORDER BY display_order"
        ).fetchall()
        return [{"mp_id": r["mp_id"], "name": r["name"]} for r in rows]
