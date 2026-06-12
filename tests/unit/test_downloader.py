"""Unit tests for the conditional report downloader (respx-mocked)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from mgi_link.config import MgiDataConfig
from mgi_link.exceptions import DownloadError
from mgi_link.ingest import downloader


@pytest.fixture
def config(tmp_path: Path) -> MgiDataConfig:
    return MgiDataConfig(data_dir=tmp_path, db_filename="mgi.sqlite")


@respx.mock
def test_download_file_200_then_304(config: MgiDataConfig) -> None:
    url = config.report_url("disease")
    route = respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="DOID:1\tname\n",
            headers={"ETag": '"v1"', "Last-Modified": "Mon, 01 Jan 2026 00:00:00 GMT"},
        )
    )
    res = downloader.download_file(config, "disease")
    assert res.not_modified is False
    assert res.path is not None and res.path.exists()
    assert res.etag == '"v1"'

    # Second call should send conditional headers; mock returns 304.
    route.mock(return_value=httpx.Response(304))
    res2 = downloader.download_file(config, "disease")
    assert res2.not_modified is True


@respx.mock
def test_download_file_http_error(config: MgiDataConfig) -> None:
    respx.get(config.report_url("disease")).mock(return_value=httpx.Response(500))
    with pytest.raises(DownloadError):
        downloader.download_file(config, "disease")


@respx.mock
def test_download_bulk_changed_flag(config: MgiDataConfig) -> None:
    for key in ("markers", "genepheno"):
        respx.get(config.report_url(key)).mock(
            return_value=httpx.Response(200, text="x\n", headers={"ETag": '"a"'})
        )
    bulk = downloader.download_bulk(config, keys=["markers", "genepheno"])
    assert bulk.changed is True
    assert bulk.path("genepheno") is not None
    assert set(bulk.validators()) == {"markers", "genepheno"}
