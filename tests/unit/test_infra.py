"""Unit tests for infra: buildinfo, logging, service adapters, refresh, app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mgi_link import buildinfo
from mgi_link.config import MgiDataConfig, settings
from mgi_link.mcp import service_adapters
from mgi_link.services import refresh


def test_build_info_keys() -> None:
    info = buildinfo.build_info()
    assert info["version"]
    assert set(info) == {"version", "git_sha", "built_at"}


def test_logging_config_returns_logger() -> None:
    from mgi_link.logging_config import configure_logging

    logger = configure_logging()
    assert logger is not None


def test_service_adapters_lifecycle(built_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "data", MgiDataConfig(data_dir=built_db.parent, db_filename=built_db.name)
    )
    service_adapters.reset_mgi_service()
    svc = service_adapters.get_mgi_service()
    assert svc.get_diagnostics()["data_available"] is True
    service_adapters.set_mgi_service(None)
    service_adapters.reset_mgi_service()


async def test_bootstrap_data_resets_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def fake_ensure(config: MgiDataConfig) -> Path:
        return config.db_path

    monkeypatch.setattr(refresh, "ensure_database", fake_ensure)
    monkeypatch.setattr(refresh, "reset_mgi_service", lambda: calls.setdefault("reset", True))

    class _Logger:
        def info(self, *a: Any, **k: Any) -> None: ...
        def warning(self, *a: Any, **k: Any) -> None: ...

    await refresh.bootstrap_data(MgiDataConfig(), _Logger())
    assert calls.get("reset") is True


def test_refresh_scheduler_disabled_returns_none() -> None:
    class _Logger:
        def info(self, *a: Any, **k: Any) -> None: ...

    config = MgiDataConfig(refresh_enabled=False)
    assert refresh.start_refresh_scheduler(config, _Logger()) is None


def test_app_health_and_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    import mgi_link.app as app_module

    async def _noop_bootstrap(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(app_module, "bootstrap_data", _noop_bootstrap)
    monkeypatch.setattr(app_module, "start_refresh_scheduler", lambda *a, **k: None)

    app = app_module.create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["service"] == "mgi-link"
        assert body["status"] == "ok"
        assert body["version"]
        assert body["transport"] == "streamable-http-stateless"
        root = client.get("/")
        assert root.json()["name"] == "mgi-link"
