"""Opt-in live MouseMine smoke test. Run with: uv run pytest -m integration."""

from __future__ import annotations

import pytest

from mgi_link.config import MouseMineConfig

pytestmark = pytest.mark.integration


def test_live_get_marker_wt1() -> None:
    from mgi_link.api.mousemine import MouseMineClient

    client = MouseMineClient(MouseMineConfig())
    try:
        marker = client.get_marker("MGI:98968")
    finally:
        client.close()
    assert marker is not None
    assert marker["symbol"] == "Wt1"
    assert marker["chromosome"]


def test_live_resolve_human_ortholog() -> None:
    from mgi_link.api.mousemine import MouseMineClient

    client = MouseMineClient(MouseMineConfig())
    try:
        ids = client.lookup_by_xref("human_symbol", "WT1")
    finally:
        client.close()
    assert "MGI:98968" in ids
