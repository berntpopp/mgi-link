"""Startup data bootstrap and the optional in-process refresh scheduler.

Cron is the recommended refresh mechanism (see docs/deployment.md), so the
in-process scheduler is OFF by default. ``bootstrap_data`` builds the index on
first start if absent — non-fatal: the server still starts and tools report
``data_unavailable`` until the build lands.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING, Any

from mgi_link.exceptions import DownloadError, MgiError
from mgi_link.ingest.builder import ensure_database, rebuild
from mgi_link.mcp.service_adapters import reset_mgi_service

if TYPE_CHECKING:
    from mgi_link.config import MgiDataConfig


async def bootstrap_data(config: MgiDataConfig, logger: Any) -> None:
    """Ensure the index exists, building it in a worker thread. Non-fatal."""
    try:
        path = await asyncio.to_thread(ensure_database, config)
        reset_mgi_service()
        # Log the filename only: the absolute path can expose local usernames.
        logger.info("mgi_data_ready", db_file=path.name)
    except (MgiError, DownloadError, OSError) as exc:
        # Log the exception TYPE only: str(exc) can embed a local path / download URL.
        logger.warning("mgi_data_bootstrap_failed", error_type=type(exc).__name__)


async def _refresh_loop(config: MgiDataConfig, logger: Any) -> None:
    interval = config.refresh_interval_hours * 3600
    while True:
        jitter = random.uniform(0, config.refresh_jitter_seconds)  # noqa: S311 - jitter only
        await asyncio.sleep(interval + jitter)
        try:
            result = await asyncio.to_thread(rebuild, config, force=False)
            if result.changed:
                reset_mgi_service()
                logger.info("mgi_data_refreshed", release=result.meta.release)
            else:
                logger.debug("mgi_data_unchanged")
        except (MgiError, DownloadError, OSError) as exc:
            logger.warning("mgi_data_refresh_failed", error_type=type(exc).__name__)


def start_refresh_scheduler(config: MgiDataConfig, logger: Any) -> asyncio.Task[None] | None:
    """Start the optional refresh loop; returns the task, or ``None`` if disabled."""
    if not config.refresh_enabled:
        return None
    logger.info("mgi_refresh_scheduler_enabled", interval_hours=config.refresh_interval_hours)
    return asyncio.create_task(_refresh_loop(config, logger))


async def stop_refresh_scheduler(task: asyncio.Task[None] | None) -> None:
    """Cancel the refresh loop task if running."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
