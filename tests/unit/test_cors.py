"""CORS hardening: an unauthenticated backend must not allow credentials.

The MGI backend holds no cookies or session, so ``allow_credentials`` is
meaningless and a footgun if origins are ever widened to ``*``. These guard
tests lock the safe posture and preserve the existing method list (GET is
served by ``/health`` and ``/``).
"""

from __future__ import annotations

from typing import Any

import pytest

import mgi_link.app as app_module


def _cors_kwargs(app: Any) -> dict[str, Any]:
    """Return the kwargs the CORSMiddleware was installed with."""
    from fastapi.middleware.cors import CORSMiddleware

    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return dict(middleware.kwargs)
    raise AssertionError("CORSMiddleware is not installed")


def _build_app(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def _noop_bootstrap(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(app_module, "bootstrap_data", _noop_bootstrap)
    monkeypatch.setattr(app_module, "start_refresh_scheduler", lambda *a, **k: None)
    return app_module.create_app()


def test_cors_credentials_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app(monkeypatch)
    assert _cors_kwargs(app)["allow_credentials"] is False


def test_cors_preserves_get_method_and_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    app = _build_app(monkeypatch)
    assert "GET" in _cors_kwargs(app)["allow_methods"]
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_cors_guard_rejects_credentials_with_wildcard() -> None:
    with pytest.raises(RuntimeError):
        app_module._assert_cors_safe(allow_credentials=True, origins=["*"])


def test_cors_guard_allows_credentials_off_with_wildcard() -> None:
    # Credentials disabled is safe even with a wildcard origin.
    app_module._assert_cors_safe(allow_credentials=False, origins=["*"])
