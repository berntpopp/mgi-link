"""Reproducible data-release build + packaging (genefoundry-router#63 option A)."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

import mgi_link.ingest.cli as cli_mod
from mgi_link.config import REPORT_FILENAMES, MgiDataConfig
from mgi_link.ingest.builder import build_database
from mgi_link.ingest.downloader import BulkDownload, DownloadResult
from mgi_link.ingest.release import package_release

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
AUTHORIZATION = ROOT / "release" / "data-authorization.json"
REPORTS = {key: FIXTURES / name for key, name in REPORT_FILENAMES.items()}
LAST_MODIFIED = "Mon, 14 Sep 2026 12:24:38 GMT"
VALIDATORS = {key: {"etag": None, "last_modified": LAST_MODIFIED} for key in REPORTS}


def _build(directory: Path) -> Path:
    config = MgiDataConfig(data_dir=directory, db_filename="mgi.sqlite")
    build_database(
        config, paths=dict(REPORTS), validators=VALIDATORS, build_utc="2026-09-14T12:24:38+00:00"
    )
    return config.db_path


def test_pinned_build_is_byte_reproducible_and_not_wal(tmp_path: Path) -> None:
    first = _build(tmp_path / "a")
    second = _build(tmp_path / "b")

    assert first.read_bytes() == second.read_bytes()
    connection = sqlite3.connect(f"file:{first}?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("SELECT build_utc, build_duration_s FROM meta").fetchone() == (
            "2026-09-14T12:24:38+00:00",
            None,
        )
    finally:
        connection.close()


def test_package_writes_verifiable_content_addressed_assets(tmp_path: Path) -> None:
    database = _build(tmp_path / "build")
    output = tmp_path / "release"

    manifest = package_release(
        database, reports=REPORTS, authorization=AUTHORIZATION, output=output, revision="0" * 40
    )

    expanded = hashlib.sha256(database.read_bytes()).hexdigest()
    assert manifest["release_tag"] == f"data-mgi-{expanded[:16]}"
    assert sorted(p.name for p in output.iterdir()) == [
        "SHA256SUMS",
        "data-authorization.json",
        "manifest.json",
        "mgi.sqlite.gz",
    ]
    bundle = output / "mgi.sqlite.gz"
    assert gzip.decompress(bundle.read_bytes()) == database.read_bytes()
    assert manifest["compressed_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert (
        manifest["source"]["sha256"]["markers"]
        == hashlib.sha256(REPORTS["markers"].read_bytes()).hexdigest()
    )
    assert manifest["license"]["spdx"] == "CC-BY-4.0"
    assert json.loads((output / "manifest.json").read_text()) == manifest
    for line in (output / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    again = package_release(
        database,
        reports=REPORTS,
        authorization=AUTHORIZATION,
        output=tmp_path / "release2",
        revision="0" * 40,
    )
    assert again["compressed_sha256"] == manifest["compressed_sha256"]


def _download(directory: Path, last_modified: str | None) -> BulkDownload:
    results = {}
    for key, source in REPORTS.items():
        target = directory / source.name
        shutil.copyfile(source, target)
        results[key] = DownloadResult(key=key, path=target, etag=None, last_modified=last_modified)
    return BulkDownload(results=results)


def test_cli_reproducible_build_then_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = MgiDataConfig(data_dir=tmp_path / "data", db_filename="mgi.sqlite")
    config.data_dir.mkdir()
    download = _download(config.data_dir, LAST_MODIFIED)
    monkeypatch.setattr(cli_mod, "get_data_config", lambda: config)
    monkeypatch.setattr(cli_mod, "download_bulk", lambda cfg, *, force=False: download)
    runner = CliRunner()

    assert runner.invoke(cli_mod.app, ["build", "--reproducible"]).exit_code == 0
    result = runner.invoke(
        cli_mod.app, ["package", "--output", str(tmp_path / "out"), "--revision", "a" * 40]
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["transformation"]["build_utc"] == "2026-09-14T12:24:38+00:00"


def test_cli_reproducible_build_requires_last_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = MgiDataConfig(data_dir=tmp_path, db_filename="mgi.sqlite")
    download = _download(tmp_path, None)
    monkeypatch.setattr(cli_mod, "get_data_config", lambda: config)
    monkeypatch.setattr(cli_mod, "download_bulk", lambda cfg, *, force=False: download)

    result = CliRunner().invoke(cli_mod.app, ["build", "--reproducible"])

    assert result.exit_code == 1
    assert not config.db_path.exists()


def test_mp_closure_order_does_not_depend_on_string_hash_seed() -> None:
    import subprocess
    import sys

    code = (
        "from pathlib import Path;from mgi_link.ingest.parser import parse_mp_obo,mp_closure_pairs;"
        f"t=parse_mp_obo(Path({str(REPORTS['mp_obo'])!r}).read_text());"
        "print(list(mp_closure_pairs(t)))"
    )
    runs = {
        subprocess.run(  # noqa: S603 - fixed argv: this interpreter + literal code
            [sys.executable, "-c", code],
            env={"PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("1", "2", "3")
    }
    assert len(runs) == 1
