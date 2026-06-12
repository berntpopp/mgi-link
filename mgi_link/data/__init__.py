"""Local data store: SQLite schema loader and read-only repository."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@lru_cache(maxsize=1)
def load_schema_sql() -> str:
    """Return the DDL used to build a fresh MGI index database."""
    return _SCHEMA_PATH.read_text(encoding="utf-8")
