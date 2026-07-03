"""Guard: pyproject -> installed metadata -> __version__ -> serverInfo -> /health are one value."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

from mgi_link import __version__
from mgi_link.app import create_app
from mgi_link.mcp.facade import create_mgi_mcp

DIST = "mgi-link"


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def test_pyproject_is_the_single_source() -> None:
    assert version(DIST) == _pyproject_version()


def test_dunder_version_is_metadata_derived() -> None:
    assert __version__ == version(DIST)


def test_mcp_server_info_version_matches_package() -> None:
    assert create_mgi_mcp().version == version(DIST)


def test_health_version_matches_package() -> None:
    resp = TestClient(create_app()).get("/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == version(DIST)
