"""Package a built MGI SQLite into an immutable, content-addressed data release.

The assets (gzip bundle, manifest, owner authorization record, ``SHA256SUMS``) are
what the ``data-release`` workflow publishes and the init sidecar later restores.
The tag is derived from the SQLite bytes, so an unchanged upstream export yields
the same tag and is never published twice.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

BUNDLE_NAME = "mgi.sqlite.gz"
_AUTHORIZATION_NAME = "data-authorization.json"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            hasher.update(chunk)
    return hasher.hexdigest()


def _meta(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM meta WHERE id = 1").fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("MGI database has no provenance (meta) row")
    return dict(row)


def package_release(
    database: Path,
    *,
    reports: dict[str, Path],
    authorization: Path,
    output: Path,
    revision: str,
) -> dict[str, Any]:
    """Write the release assets into the new directory *output*; return the manifest."""
    record = json.loads(authorization.read_text(encoding="utf-8"))
    if record.get("redistribution_allowed") is not True:
        raise ValueError("data authorization does not allow redistribution")
    meta = _meta(database)
    if meta["build_duration_s"] is not None:
        raise ValueError("database was not built reproducibly (pass a pinned build time)")
    output.mkdir(parents=True)
    bundle = output / BUNDLE_NAME
    with (
        database.open("rb") as source,
        bundle.open("xb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as packed,
    ):
        shutil.copyfileobj(source, packed, 1 << 20)
    shutil.copyfile(authorization, output / _AUTHORIZATION_NAME)
    expanded = _sha256(database)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "release_tag": f"data-mgi-{expanded[:16]}",
        "bundle": BUNDLE_NAME,
        "compressed_sha256": _sha256(bundle),
        "expanded_sha256": expanded,
        "expanded_bytes": database.stat().st_size,
        "data_schema_version": meta["schema_version"],
        "source": {
            "reports_base_url": meta["reports_base_url"],
            "release": meta["release"],
            "validators": json.loads(meta["source_validators"]),
            "sha256": {key: _sha256(path) for key, path in sorted(reports.items())},
        },
        "record_counts": {
            "markers": meta["marker_count"],
            "alleles": meta["allele_count"],
            "genopheno": meta["genopheno_count"],
            "mp_terms": meta["mp_term_count"],
            "orthologs": meta["ortholog_count"],
            "disease_models": meta["disease_count"],
        },
        "transformation": {
            "repository": "https://github.com/berntpopp/mgi-link",
            "revision": revision,
            "build_utc": meta["build_utc"],
        },
        "license": {
            "spdx": record["license"]["spdx"],
            "url": record["license"]["url"],
            "terms_url": record["license"]["terms_url"],
        },
        "attribution": record["attribution"],
        "authorization": {"reviewer": record["reviewer"], "reviewed_at": record["reviewed_at"]},
        "disclaimer": record["disclaimer"],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    names = (BUNDLE_NAME, _AUTHORIZATION_NAME, "manifest.json")
    (output / "SHA256SUMS").write_text(
        "".join(f"{_sha256(output / name)}  {name}\n" for name in names), encoding="utf-8"
    )
    return manifest
