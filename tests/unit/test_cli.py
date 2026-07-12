"""Unit tests for the mgi-link-data CLI (download mocked, real fixture build)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mgi_link.config import REPORT_FILENAMES, MgiDataConfig
from mgi_link.ingest import builder, cli
from mgi_link.ingest.downloader import BulkDownload, DownloadResult

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
runner = CliRunner()


@pytest.fixture
def patched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MgiDataConfig:
    config = MgiDataConfig(data_dir=tmp_path, db_filename="mgi.sqlite")
    monkeypatch.setattr(cli, "get_data_config", lambda: config)

    def fake_download_bulk(_config: MgiDataConfig, *, force: bool = False) -> BulkDownload:
        bulk = BulkDownload()
        for key, filename in REPORT_FILENAMES.items():
            bulk.results[key] = DownloadResult(
                key=key, path=FIXTURES / filename, last_modified="Fri, 12 Jun 2026 12:00:00 GMT"
            )
        return bulk

    monkeypatch.setattr(cli, "download_bulk", fake_download_bulk)
    # ``refresh`` delegates to ``builder.rebuild``, whose global dependency is
    # ``builder.download_bulk`` rather than the CLI import used by ``build``.
    monkeypatch.setattr(builder, "download_bulk", fake_download_bulk)
    return config


def test_cli_build_then_status(patched: MgiDataConfig) -> None:
    result = runner.invoke(cli.app, ["build"])
    assert result.exit_code == 0, result.output
    assert "Built MGI database" in result.output
    assert patched.db_path.exists()

    status = runner.invoke(cli.app, ["status"])
    assert status.exit_code == 0
    assert "markers" in status.output


def test_cli_status_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = MgiDataConfig(data_dir=tmp_path, db_filename="absent.sqlite")
    monkeypatch.setattr(cli, "get_data_config", lambda: config)
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 1
    assert "No MGI database" in result.output


def test_cli_refresh_builds(patched: MgiDataConfig) -> None:
    result = runner.invoke(cli.app, ["refresh"])
    assert result.exit_code == 0, result.output
    assert "refreshed" in result.output.lower()
    assert patched.db_path.exists()
