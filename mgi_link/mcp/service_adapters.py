"""Lazily-constructed singleton MgiService for MCP tools.

The repository is opened against the already-built SQLite index (the server
lifespan bootstraps it in a background thread; see ``mgi_link.app``). If the
index is not present yet, the service is built without a repository — tools then
return ``data_unavailable``.
"""

from __future__ import annotations

import logging

from mgi_link.api.mousemine import MouseMineClient
from mgi_link.config import settings
from mgi_link.data.repository import MgiRepository
from mgi_link.exceptions import DataUnavailableError
from mgi_link.redaction import redact_url
from mgi_link.services.mgi_service import MgiService

logger = logging.getLogger(__name__)

_service: MgiService | None = None


def _build_service() -> MgiService:
    repo: MgiRepository | None = None
    db_path = settings.data.db_path
    if db_path.exists():
        try:
            repo = MgiRepository(db_path)
        except DataUnavailableError as exc:  # pragma: no cover - corrupt db
            # Filename only: the absolute path can expose local usernames.
            logger.warning("mgi_repo_open_failed db_file=%s err=%s", db_path.name, exc)
    fallback: MouseMineClient | None = None
    if settings.mousemine.enable_live_fallback:
        logger.info(
            "mgi_live_fallback_enabled base_url=%s", redact_url(settings.mousemine.base_url)
        )
        fallback = MouseMineClient(settings.mousemine)
    return MgiService(repo, fallback=fallback)


def get_mgi_service() -> MgiService:
    """Return a process-wide :class:`MgiService` (built on first use)."""
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def reset_mgi_service() -> None:
    """Drop the cached service (closing its fallback client) so the next call re-opens."""
    global _service
    if _service is not None:
        _service.close()
    _service = None


def set_mgi_service(service: MgiService | None) -> None:
    """Override the singleton (used by tests); closes any previous service."""
    global _service
    if _service is not None and _service is not service:
        _service.close()
    _service = service
