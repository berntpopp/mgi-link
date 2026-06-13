"""Shared fixtures: a fixture-backed MGI index, repository, service, and facade."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mgi_link.config import REPORT_FILENAMES, MgiDataConfig
from mgi_link.data.repository import MgiRepository
from mgi_link.ingest.builder import build_database
from mgi_link.services.mgi_service import MgiService

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _structured(result: Any) -> dict[str, Any]:
    """Read structured_content defensively (with TextContent JSON fallback)."""
    sc = result.structured_content
    if isinstance(sc, dict):
        return sc
    return json.loads(result.content[0].text)


@pytest.fixture
def structured() -> Any:
    """Expose the structured-content reader to tests."""
    return _structured


@pytest.fixture(scope="session")
def built_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a small MGI index from the real fixture reports once per session."""
    data_dir = tmp_path_factory.mktemp("mgi_data")
    config = MgiDataConfig(data_dir=data_dir, db_filename="mgi.sqlite")
    paths: dict[str, Path | None] = {
        key: FIXTURES_DIR / filename for key, filename in REPORT_FILENAMES.items()
    }
    validators = {
        key: {"etag": None, "last_modified": "Fri, 12 Jun 2026 12:00:00 GMT"} for key in paths
    }
    build_database(config, paths=paths, validators=validators)
    return config.db_path


@pytest.fixture
def repo(built_db: Path) -> Any:
    """An open read-only repository over the fixture database."""
    repository = MgiRepository(built_db)
    yield repository
    repository.close()


@pytest.fixture
def service(repo: MgiRepository) -> MgiService:
    """A service backed by the fixture repository."""
    return MgiService(repo)


@pytest.fixture
def facade(service: MgiService) -> Any:
    """A FastMCP facade with the fixture service injected; cleans up after."""
    from mgi_link.mcp.facade import create_mgi_mcp
    from mgi_link.mcp.service_adapters import set_mgi_service

    set_mgi_service(service)
    mcp = create_mgi_mcp()
    yield mcp
    set_mgi_service(None)


@pytest.fixture
def fallback_facade() -> Any:
    """A FastMCP facade whose service has no repo, only a fake MouseMine fallback."""
    from mgi_link.mcp.facade import create_mgi_mcp
    from mgi_link.mcp.service_adapters import set_mgi_service
    from mgi_link.services.mgi_service import MgiService
    from tests.unit.test_marker_provider import _FakeProvider

    set_mgi_service(MgiService(None, fallback=_FakeProvider()))
    mcp = create_mgi_mcp()
    yield mcp
    set_mgi_service(None)


@pytest.fixture
def cold_facade() -> Any:
    """A FastMCP facade whose service has neither repo nor fallback (cold start)."""
    from mgi_link.mcp.facade import create_mgi_mcp
    from mgi_link.mcp.service_adapters import set_mgi_service
    from mgi_link.services.mgi_service import MgiService

    set_mgi_service(MgiService(None))
    mcp = create_mgi_mcp()
    yield mcp
    set_mgi_service(None)
