"""Conditional download of the MGI bulk data reports.

MGI publishes tab-delimited ``.rpt`` reports that honour ``ETag`` /
``Last-Modified``. We cache the last-seen validators per URL and issue
conditional ``GET`` requests, so a re-download only transfers a body when the
upstream data actually changed (a weekly cron check is then almost always a
cheap ``304``). The phenotype report (``genepheno``) is the primary trigger for
a rebuild.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from mgi_link.config import PRIMARY_REPORT_KEY, REPORT_FILENAMES
from mgi_link.exceptions import DownloadError

if TYPE_CHECKING:
    from mgi_link.config import MgiDataConfig

CACHE_FILENAME = "download_cache.json"
_CHUNK_SIZE = 1 << 16


@dataclass
class DownloadResult:
    """Outcome of a conditional download of one report."""

    key: str
    path: Path | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    content_length: int | None = None


@dataclass
class BulkDownload:
    """Outcome of downloading a set of reports together."""

    results: dict[str, DownloadResult] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        """True when the primary report transferred a fresh body this call."""
        primary = self.results.get(PRIMARY_REPORT_KEY)
        if primary is not None and not primary.not_modified:
            return True
        # Fall back to "any report changed" if the primary was absent.
        return any(not r.not_modified for r in self.results.values())

    def path(self, key: str) -> Path | None:
        """Local path for a report key (``None`` if not downloaded)."""
        res = self.results.get(key)
        return res.path if res is not None else None

    def validators(self) -> dict[str, dict[str, str | None]]:
        """Per-report ``{etag, last_modified}`` for provenance."""
        return {
            key: {"etag": r.etag, "last_modified": r.last_modified}
            for key, r in self.results.items()
        }


def _cache_path(config: MgiDataConfig) -> Path:
    return config.data_dir / CACHE_FILENAME


def _read_cache(config: MgiDataConfig) -> dict[str, dict[str, str | None]]:
    cache_path = _cache_path(config)
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(
    config: MgiDataConfig, url: str, *, etag: str | None, last_modified: str | None
) -> None:
    cache_path = _cache_path(config)
    data = _read_cache(config)
    data[url] = {"etag": etag, "last_modified": last_modified}
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stream_to_file(response: httpx.Response, path: Path) -> None:
    with path.open("wb") as handle:
        for chunk in response.iter_bytes(_CHUNK_SIZE):
            handle.write(chunk)


def download_file(
    config: MgiDataConfig,
    key: str,
    *,
    force: bool = False,
) -> DownloadResult:
    """Conditionally download the report ``key`` to ``data_dir/<filename>``.

    Sends ``If-None-Match`` / ``If-Modified-Since`` from the cache unless
    ``force``. A ``304`` reuses the existing local file without a body transfer.
    """
    config.data_dir.mkdir(parents=True, exist_ok=True)
    url = config.report_url(key)
    filename = REPORT_FILENAMES[key]
    dest = config.data_dir / filename
    headers = {"User-Agent": config.user_agent}
    if not force:
        cached = _read_cache(config).get(url, {})
        if cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = str(cached["last_modified"])

    try:
        with (
            httpx.Client(follow_redirects=True, timeout=config.download_timeout) as client,
            client.stream("GET", url, headers=headers) as response,
        ):
            if response.status_code == httpx.codes.NOT_MODIFIED:
                return DownloadResult(
                    key=key,
                    path=dest if dest.exists() else None,
                    etag=headers.get("If-None-Match"),
                    last_modified=headers.get("If-Modified-Since"),
                    not_modified=True,
                )
            response.raise_for_status()
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            content_length = _int_or_none(response.headers.get("Content-Length"))
            _stream_to_file(response, dest)
    except httpx.HTTPStatusError as exc:
        raise DownloadError(
            f"GET {url} failed: {exc.response.status_code}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"GET {url} failed: {exc}") from exc

    _write_cache(config, url, etag=etag, last_modified=last_modified)
    return DownloadResult(
        key=key,
        path=dest,
        etag=etag,
        last_modified=last_modified,
        not_modified=False,
        content_length=content_length,
    )


def download_bulk(
    config: MgiDataConfig, *, keys: list[str] | None = None, force: bool = False
) -> BulkDownload:
    """Download the configured MGI reports (conditionally unless ``force``)."""
    selected = keys if keys is not None else list(REPORT_FILENAMES)
    bulk = BulkDownload()
    for key in selected:
        bulk.results[key] = download_file(config, key, force=force)
    return bulk
