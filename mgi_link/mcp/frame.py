"""The success frame of the Response-Envelope Standard (v1) and its v1.2 provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mgi_link.exceptions import DataUnavailableError
from mgi_link.mcp.service_adapters import get_mgi_service


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _provenance(started: datetime) -> dict[str, str]:
    """Where the data of this call came from: the local index, or live MouseMine.

    For the index, ``retrieved_at`` is its build time: a build downloads the reports and
    indexes them in one step (a release build pins it to the newest report's
    ``Last-Modified``). MouseMine reports no release, so its data is ``live`` and dated to
    the call.
    """
    service = get_mgi_service()
    if service.using_fallback:
        return {"source": "mousemine", "data_version": "live", "retrieved_at": _utc(started)}
    try:
        meta = service.repo.get_meta()
    except DataUnavailableError:  # only the ops tools succeed without an index
        return {}
    return {
        "source": "mgi",
        "data_version": meta["release"] or "unknown",
        "retrieved_at": _utc(datetime.fromisoformat(meta["build_utc"])),
    }


def frame_success(
    payload: dict[str, Any], meta: dict[str, Any], started: datetime
) -> dict[str, Any]:
    """Frame a tool body's dict as ``{success, result | results, _meta}``.

    ``meta`` wins over the ``_meta`` the body set itself. A body that names neither
    ``result`` nor ``results`` is one record and goes under ``result``.
    """
    meta = {**(payload.pop("_meta", None) or {}), **meta}
    success = payload.pop("success", True)
    if success:
        meta.update(_provenance(started))
        if "total" in payload and "truncated" in payload:
            # These tools page by `limit` only: there is no cursor, a wider `limit` gets the rest.
            meta["pagination"] = {
                "total_count": payload["total"],
                "has_more": payload["truncated"],
                "next_cursor": None,
            }
        if not {"result", "results"} & payload.keys():
            payload = {"result": payload}
    return {"success": success, **payload, "_meta": meta}
