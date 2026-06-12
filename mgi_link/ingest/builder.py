"""Atomic SQLite builder for the MGI bulk reports.

Streams markers, alleles, gene->phenotype annotations, the MP vocabulary +
ontology closure, mouse-human orthologs, and disease models into a temporary
database, then atomically swaps the finished file into place. Callers get back a
typed :class:`BuildMeta`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mgi_link.constants import SCHEMA_VERSION
from mgi_link.data import load_schema_sql
from mgi_link.exceptions import DataUnavailableError
from mgi_link.ingest.downloader import BulkDownload, download_bulk
from mgi_link.ingest.lock import build_lock
from mgi_link.ingest.parser import (
    iter_alleles,
    iter_disease_models,
    iter_genepheno,
    iter_marker_ensembl,
    iter_markers,
    iter_mp_terms,
    iter_orthologs,
    mp_closure_pairs,
    mp_top_systems,
    parse_mp_obo,
)

if TYPE_CHECKING:
    from mgi_link.config import MgiDataConfig

_BATCH = 2000


@dataclass
class BuildMeta:
    """Provenance for a built MGI index database (one ``meta`` row)."""

    schema_version: int
    release: str | None
    reports_base_url: str
    source_validators: str
    marker_count: int
    allele_count: int
    genopheno_count: int
    mp_term_count: int
    ortholog_count: int
    disease_count: int
    build_utc: str
    build_duration_s: float | None


@dataclass
class RebuildResult:
    """Outcome of a conditional refresh/rebuild."""

    meta: BuildMeta
    changed: bool
    not_modified: bool


def _executemany(conn: sqlite3.Connection, sql: str, rows: list[tuple[Any, ...]]) -> None:
    if rows:
        conn.executemany(sql, rows)


def _load_markers(
    conn: sqlite3.Connection,
    path: Path,
    *,
    ensembl_map: dict[str, str],
    entrez_map: dict[str, str],
) -> int:
    marker_sql = (
        "INSERT OR REPLACE INTO marker (mgi_id, symbol, symbol_upper, name, marker_type, "
        "feature_type, chromosome, cm_position, coord_start, coord_end, strand, status, "
        "entrez_id, ensembl_gene_id, refseq_id, synonyms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    lookup_sql = "INSERT INTO marker_lookup (lookup_symbol, mgi_id, symbol_type) VALUES (?, ?, ?)"
    fts_sql = "INSERT INTO marker_fts (mgi_id, symbol, name, synonyms) VALUES (?, ?, ?, ?)"
    xref_sql = "INSERT INTO xref (source, value_upper, value, mgi_id) VALUES (?, ?, ?, ?)"

    markers: list[tuple[Any, ...]] = []
    lookups: list[tuple[str, str, str]] = []
    fts: list[tuple[Any, ...]] = []
    xrefs: list[tuple[str, str, str, str]] = []
    count = 0

    def flush() -> None:
        _executemany(conn, marker_sql, markers)
        _executemany(conn, lookup_sql, lookups)
        _executemany(conn, fts_sql, fts)
        _executemany(conn, xref_sql, xrefs)
        markers.clear()
        lookups.clear()
        fts.clear()
        xrefs.clear()

    for m in iter_markers(path):
        mgi_id = m["mgi_id"]
        symbol = m["symbol"]
        ensembl = ensembl_map.get(mgi_id)
        entrez = entrez_map.get(mgi_id)
        synonyms = m["synonyms"]
        markers.append(
            (
                mgi_id,
                symbol,
                symbol.upper(),
                m["name"],
                m["marker_type"],
                m["feature_type"],
                m["chromosome"],
                m["cm_position"],
                m["coord_start"],
                m["coord_end"],
                m["strand"],
                m["status"],
                entrez,
                ensembl,
                None,
                json.dumps(synonyms),
            )
        )
        lookups.append((symbol.upper(), mgi_id, "current"))
        for syn in synonyms:
            lookups.append((syn.upper(), mgi_id, "synonym"))
        fts.append((mgi_id, symbol, m["name"] or "", " ".join(synonyms)))
        if entrez:
            xrefs.append(("entrez_id", entrez.upper(), entrez, mgi_id))
        if ensembl:
            xrefs.append(("ensembl_gene_id", ensembl.upper(), ensembl, mgi_id))
        count += 1
        if len(markers) >= _BATCH:
            flush()
    flush()
    return count


def _load_orthologs(conn: sqlite3.Connection, path: Path) -> int:
    ortho_sql = (
        "INSERT OR REPLACE INTO ortholog (mgi_id, mouse_symbol, human_symbol, "
        "human_entrez_id, hgnc_id, omim_gene_id, human_ensembl_id, human_coords) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    xref_sql = "INSERT INTO xref (source, value_upper, value, mgi_id) VALUES (?, ?, ?, ?)"
    orthos: list[tuple[Any, ...]] = []
    xrefs: list[tuple[str, str, str, str]] = []
    count = 0
    for o in iter_orthologs(path):
        mgi_id = o["mgi_id"]
        if not mgi_id:
            continue
        orthos.append(
            (
                mgi_id,
                o["mouse_symbol"],
                o["human_symbol"],
                o["human_entrez_id"],
                o["hgnc_id"],
                o["omim_gene_id"],
                o["human_ensembl_id"],
                o["human_coords"],
            )
        )
        for source in ("human_symbol", "hgnc_id", "omim_gene_id", "human_entrez_id"):
            val = o.get(source)
            if val:
                xrefs.append((source, val.upper(), val, mgi_id))
        count += 1
        if len(orthos) >= _BATCH:
            _executemany(conn, ortho_sql, orthos)
            _executemany(conn, xref_sql, xrefs)
            orthos.clear()
            xrefs.clear()
    _executemany(conn, ortho_sql, orthos)
    _executemany(conn, xref_sql, xrefs)
    return count


def _load_alleles(conn: sqlite3.Connection, path: Path) -> int:
    sql = (
        "INSERT OR REPLACE INTO allele (allele_id, symbol, name, allele_type, attributes, "
        "pubmed_ids, marker_id, marker_symbol) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    batch: list[tuple[Any, ...]] = []
    count = 0
    for a in iter_alleles(path):
        batch.append(
            (
                a["allele_id"],
                a["symbol"],
                a["name"],
                a["allele_type"],
                json.dumps(a["attributes"]),
                json.dumps(a["pubmed_ids"]),
                a["marker_id"],
                a["marker_symbol"],
            )
        )
        count += 1
        if len(batch) >= _BATCH:
            _executemany(conn, sql, batch)
            batch.clear()
    _executemany(conn, sql, batch)
    return count


def _load_genepheno(conn: sqlite3.Connection, path: Path) -> int:
    sql = (
        "INSERT INTO genopheno (marker_id, mp_id, allelic_composition, allele_symbols, "
        "allele_ids, genetic_background, pubmed_id, genotype_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    batch: list[tuple[Any, ...]] = []
    count = 0
    for g in iter_genepheno(path):
        batch.append(
            (
                g["marker_id"],
                g["mp_id"],
                g["allelic_composition"],
                g["allele_symbols"],
                json.dumps(g["allele_ids"]),
                g["genetic_background"],
                g["pubmed_id"],
                g["genotype_id"],
            )
        )
        count += 1
        if len(batch) >= _BATCH:
            _executemany(conn, sql, batch)
            batch.clear()
    _executemany(conn, sql, batch)
    return count


def _load_mp_terms(conn: sqlite3.Connection, path: Path) -> int:
    term_sql = "INSERT OR REPLACE INTO mp_term (mp_id, name, definition) VALUES (?, ?, ?)"
    fts_sql = "INSERT INTO mp_fts (mp_id, name, definition) VALUES (?, ?, ?)"
    terms: list[tuple[Any, ...]] = []
    fts: list[tuple[Any, ...]] = []
    count = 0
    for t in iter_mp_terms(path):
        terms.append((t["mp_id"], t["name"], t["definition"]))
        fts.append((t["mp_id"], t["name"], t["definition"] or ""))
        count += 1
        if len(terms) >= _BATCH:
            _executemany(conn, term_sql, terms)
            _executemany(conn, fts_sql, fts)
            terms.clear()
            fts.clear()
    _executemany(conn, term_sql, terms)
    _executemany(conn, fts_sql, fts)
    return count


def _load_mp_graph(conn: sqlite3.Connection, path: Path) -> None:
    terms = parse_mp_obo(path.read_text(encoding="utf-8", errors="replace"))
    closure_sql = "INSERT INTO mp_closure (mp_id, ancestor_id) VALUES (?, ?)"
    batch: list[tuple[str, str]] = []
    for pair in mp_closure_pairs(terms):
        batch.append(pair)
        if len(batch) >= _BATCH:
            _executemany(conn, closure_sql, batch)
            batch.clear()
    _executemany(conn, closure_sql, batch)
    parent_sql = "INSERT INTO mp_parent (mp_id, parent_id) VALUES (?, ?)"
    parent_rows = [
        (mp_id, parent) for mp_id, term in terms.items() for parent in term.get("parents", [])
    ]
    _executemany(conn, parent_sql, parent_rows)
    system_sql = (
        "INSERT OR REPLACE INTO mp_top_system (mp_id, name, display_order) VALUES (?, ?, ?)"
    )
    _executemany(
        conn, system_sql, [(mp_id, name, order) for mp_id, name, order in mp_top_systems(terms)]
    )


def _load_diseases(conn: sqlite3.Connection, path: Path) -> int:
    sql = "INSERT INTO disease_model (marker_id, doid, disease_name, omim_ids) VALUES (?, ?, ?, ?)"
    batch: list[tuple[Any, ...]] = []
    count = 0
    for d in iter_disease_models(path):
        batch.append((d["marker_id"], d["doid"], d["disease_name"], json.dumps(d["omim_ids"])))
        count += 1
        if len(batch) >= _BATCH:
            _executemany(conn, sql, batch)
            batch.clear()
    _executemany(conn, sql, batch)
    return count


def _insert_meta(conn: sqlite3.Connection, meta: BuildMeta) -> None:
    values = asdict(meta)
    columns = list(values.keys())  # dataclass field names, not user input
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    conn.execute(
        f"INSERT INTO meta (id, {col_list}) VALUES (1, {placeholders})",  # noqa: S608
        tuple(values[col] for col in columns),
    )


def _release_from_validators(validators: dict[str, dict[str, str | None]]) -> str | None:
    """Best-effort release date from the primary report's Last-Modified."""
    for key in ("genepheno", "alleles", "markers"):
        lm = validators.get(key, {}).get("last_modified")
        if lm:
            return lm
    return None


def build_database(
    config: MgiDataConfig,
    *,
    paths: dict[str, Path | None],
    validators: dict[str, dict[str, str | None]],
) -> BuildMeta:
    """Build the MGI SQLite index from the report files, atomically."""
    start = time.perf_counter()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=config.data_dir, suffix=".sqlite.tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)

    def _need(key: str) -> Path:
        p = paths.get(key)
        if p is None or not p.exists():
            raise DataUnavailableError(f"Required MGI report '{key}' missing; cannot build index.")
        return p

    try:
        conn = sqlite3.connect(tmp_path)
        try:
            conn.executescript(load_schema_sql())

            ensembl_map: dict[str, str] = {}
            ensembl_path = paths.get("ensembl")
            if ensembl_path is not None and ensembl_path.exists():
                ensembl_map = dict(iter_marker_ensembl(ensembl_path))
            entrez_map: dict[str, str] = {
                o["mgi_id"]: o["mouse_entrez_id"]
                for o in iter_orthologs(_need("ortholog"))
                if o["mgi_id"] and o["mouse_entrez_id"]
            }

            marker_count = _load_markers(
                conn, _need("markers"), ensembl_map=ensembl_map, entrez_map=entrez_map
            )
            ortholog_count = _load_orthologs(conn, _need("ortholog"))
            allele_count = _load_alleles(conn, _need("alleles"))
            genopheno_count = _load_genepheno(conn, _need("genepheno"))
            mp_term_count = _load_mp_terms(conn, _need("mp_vocab"))
            _load_mp_graph(conn, _need("mp_obo"))
            disease_count = _load_diseases(conn, _need("disease"))

            conn.execute("INSERT INTO marker_fts(marker_fts) VALUES ('optimize')")
            conn.execute("INSERT INTO mp_fts(mp_fts) VALUES ('optimize')")

            meta = BuildMeta(
                schema_version=SCHEMA_VERSION,
                release=_release_from_validators(validators),
                reports_base_url=config.reports_base_url,
                source_validators=json.dumps(validators),
                marker_count=marker_count,
                allele_count=allele_count,
                genopheno_count=genopheno_count,
                mp_term_count=mp_term_count,
                ortholog_count=ortholog_count,
                disease_count=disease_count,
                build_utc=datetime.now(tz=UTC).isoformat(),
                build_duration_s=round(time.perf_counter() - start, 3),
            )
            _insert_meta(conn, meta)
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp_path, config.db_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return meta


def read_meta(db_path: Path) -> BuildMeta | None:
    """Read provenance from an existing database, or ``None`` if absent."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return BuildMeta(
        schema_version=row["schema_version"],
        release=row["release"],
        reports_base_url=row["reports_base_url"],
        source_validators=row["source_validators"],
        marker_count=row["marker_count"],
        allele_count=row["allele_count"],
        genopheno_count=row["genopheno_count"],
        mp_term_count=row["mp_term_count"],
        ortholog_count=row["ortholog_count"],
        disease_count=row["disease_count"],
        build_utc=row["build_utc"],
        build_duration_s=row["build_duration_s"],
    )


def _build_from_download(config: MgiDataConfig, download: BulkDownload) -> BuildMeta:
    paths = {key: download.path(key) for key in download.results}
    return build_database(config, paths=paths, validators=download.validators())


def ensure_database(config: MgiDataConfig) -> Path:
    """Return the database path, building it on first use if configured."""
    if config.db_path.exists():
        return config.db_path
    if not config.auto_bootstrap:
        raise DataUnavailableError(
            "MGI database not built. Run `mgi-link-data build` (or `make data`)."
        )
    with build_lock(config.data_dir, timeout=config.build_lock_timeout):
        if config.db_path.exists():  # double-checked locking
            return config.db_path
        download = download_bulk(config)
        _build_from_download(config, download)
    return config.db_path


def rebuild(config: MgiDataConfig, *, force: bool) -> RebuildResult:
    """Download (conditionally) and rebuild the database under the build lock."""
    with build_lock(config.data_dir, timeout=config.build_lock_timeout):
        download = download_bulk(config, force=force)
        if not download.changed and config.db_path.exists():
            existing = read_meta(config.db_path)
            if existing is not None:
                return RebuildResult(meta=existing, changed=False, not_modified=True)
        meta = _build_from_download(config, download)
    return RebuildResult(meta=meta, changed=True, not_modified=False)
