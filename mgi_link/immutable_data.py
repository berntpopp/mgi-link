"""Restore the one reviewed MGI data release and verify what the server serves.

``materialize_immutable_data`` runs only in the short-lived init sidecar: it
downloads the pinned GitHub release asset, verifies the compressed and expanded
digests, and atomically points ``<root>/current`` at ``<root>/<compressed_sha256>``.
``verify_runtime_identity`` is what ``/health`` reports to the fleet release
gate (Runtime Data Identity v1): it re-proves that the served file is that exact
release, never trusting configuration alone.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from mgi_link.config import ImmutableDataRequirement
from mgi_link.constants import SCHEMA_VERSION
from mgi_link.exceptions import DataUnavailableError

DATABASE_NAME = "mgi.sqlite"
_SQLITE_HEADER = b"SQLite format 3\x00"
_ALLOWED_HOSTS = frozenset(
    {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
)
_MAX_REDIRECTS = 5
_CHUNK = 1 << 20
_VERIFIED: set[tuple[str, int, int, int, str]] = set()


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def _fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if path.is_dir() else 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _identity(requirement: ImmutableDataRequirement) -> dict[str, str]:
    return {
        "release_tag": requirement.release_tag,
        "compressed_sha256": requirement.compressed_sha256,
        "expanded_sha256": requirement.expanded_sha256,
    }


def _download(requirement: ImmutableDataRequirement, destination: Path) -> None:
    """Fetch the bundle over HTTPS, following redirects only to GitHub asset hosts."""
    url = str(requirement.bundle_url)
    hasher = hashlib.sha256()
    try:
        with httpx.Client(follow_redirects=False, timeout=300) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                parts = urlsplit(url)
                if parts.scheme != "https" or parts.hostname not in _ALLOWED_HOSTS:
                    raise DataUnavailableError("MGI data bundle URL left the allowed hosts")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers["location"])
                        continue
                    response.raise_for_status()
                    written = 0
                    with destination.open("xb") as handle:
                        for chunk in response.iter_bytes(1 << 16):
                            written += len(chunk)
                            if written > requirement.max_compressed_bytes:
                                raise DataUnavailableError("MGI data bundle exceeds its limit")
                            hasher.update(chunk)
                            handle.write(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
                    break
            else:
                raise DataUnavailableError("MGI data bundle download redirected too often")
    except (httpx.HTTPError, OSError, KeyError) as exc:
        raise DataUnavailableError("MGI data bundle download failed") from exc
    if hasher.hexdigest() != requirement.compressed_sha256:
        raise DataUnavailableError("MGI data bundle digest verification failed")


def _decompress(requirement: ImmutableDataRequirement, source: Path, database: Path) -> None:
    written = 0
    try:
        with gzip.open(source, "rb") as stream, database.open("xb") as handle:
            while chunk := stream.read(_CHUNK):
                written += len(chunk)
                if written > requirement.max_expanded_bytes:
                    raise DataUnavailableError("MGI database exceeds its expanded limit")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise DataUnavailableError("MGI data bundle decompression failed") from exc


def _verify_database(requirement: ImmutableDataRequirement, database: Path) -> None:
    """Prove the exact expanded bytes, then that they are a MGI schema database."""
    with database.open("rb") as handle:
        if handle.read(len(_SQLITE_HEADER)) != _SQLITE_HEADER:
            raise DataUnavailableError("MGI data bundle is not a SQLite database")
    if _sha256(database) != requirement.expanded_sha256:
        raise DataUnavailableError("MGI database expanded digest verification failed")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
        try:
            row = connection.execute("SELECT schema_version FROM meta WHERE id = 1").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DataUnavailableError("MGI database metadata verification failed") from exc
    if row != (SCHEMA_VERSION,):
        raise DataUnavailableError("MGI database schema does not match this application")


def _write_identity(requirement: ImmutableDataRequirement, directory: Path) -> None:
    temporary = directory / ".identity.json.tmp"
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(_identity(requirement), handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    target = directory / "identity.json"
    os.replace(temporary, target)
    os.chmod(target, 0o444)


def _read_identity(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise DataUnavailableError("MGI data release identity is unavailable")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataUnavailableError("MGI data release identity is invalid") from exc


def materialize_immutable_data(requirement: ImmutableDataRequirement) -> Path:
    """Download, verify, and atomically select the pinned release; return the database.

    An already materialized, still-valid snapshot is re-verified and reselected
    without a download. ``current`` changes only after every check passed.
    """
    root = requirement.reference_root
    root.mkdir(mode=0o755, parents=True, exist_ok=True)
    target = root / requirement.compressed_sha256
    staging = root / f".{requirement.compressed_sha256}.staging-{os.getpid()}"
    with (root / ".materialize.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if target.is_dir():
                if _read_identity(target / "identity.json") != _identity(requirement):
                    raise DataUnavailableError("existing MGI snapshot has a different identity")
                _verify_database(requirement, target / DATABASE_NAME)
            else:
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir(mode=0o700)
                bundle = staging / "mgi.sqlite.gz"
                _download(requirement, bundle)
                database = staging / DATABASE_NAME
                _decompress(requirement, bundle, database)
                bundle.unlink()
                os.chmod(database, 0o444)
                _verify_database(requirement, database)
                _write_identity(requirement, staging)
                _fsync(staging)
                os.replace(staging, target)
            link = root / f".current-{os.getpid()}"
            link.unlink(missing_ok=True)
            link.symlink_to(requirement.compressed_sha256)
            os.replace(link, root / "current")
            _fsync(root)
            return target / DATABASE_NAME
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            fcntl.flock(lock, fcntl.LOCK_UN)


def expected_identity(requirement: ImmutableDataRequirement) -> dict[str, str]:
    """Public release identity derived from validated configuration alone."""
    return {
        "release_tag": requirement.release_tag,
        "digest": f"sha256:{requirement.compressed_sha256}",
    }


def verify_runtime_identity(
    database: Path, requirement: ImmutableDataRequirement
) -> dict[str, str]:
    """Prove the served SQLite file is the pinned release; return its public identity."""
    try:
        resolved = database.resolve(strict=True)
    except OSError as exc:
        raise DataUnavailableError("MGI database is unavailable") from exc
    if (
        resolved.name != DATABASE_NAME
        or not resolved.is_file()
        or resolved.parent.name != requirement.compressed_sha256
    ):
        raise DataUnavailableError("MGI database is not the pinned data release")
    if _read_identity(resolved.parent / "identity.json") != _identity(requirement):
        raise DataUnavailableError("MGI data release identity does not match its pin")
    # Hashing ~400 MB on every /health probe is too costly: re-hash only when the
    # served file's identity (inode, size, mtime) changes.
    stat = resolved.stat()
    key = (str(resolved), stat.st_ino, stat.st_size, stat.st_mtime_ns, requirement.expanded_sha256)
    if key not in _VERIFIED:
        _verify_database(requirement, resolved)
        _VERIFIED.add(key)
    return expected_identity(requirement)
