"""Lazily-constructed singleton MgiService for MCP tools.

The repository is opened against the already-built SQLite index (the server
lifespan bootstraps it in a background thread; see ``mgi_link.app``). If the
index is not present yet, the service is built without a repository — tools then
return ``data_unavailable``.
"""

from __future__ import annotations

import logging

from mgi_link.config import settings
from mgi_link.data.repository import MgiRepository
from mgi_link.exceptions import DataUnavailableError
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
            logger.warning("mgi_repo_open_failed path=%s err=%s", db_path, exc)
    return MgiService(repo)


def get_mgi_service() -> MgiService:
    """Return a process-wide :class:`MgiService` (built on first use)."""
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def reset_mgi_service() -> None:
    """Drop the cached service so the next call re-opens the (refreshed) index."""
    global _service
    _service = None


def set_mgi_service(service: MgiService | None) -> None:
    """Override the singleton (used by tests)."""
    global _service
    _service = service
