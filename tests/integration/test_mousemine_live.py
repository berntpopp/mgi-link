"""Opt-in live MouseMine smoke test. Run with: uv run pytest -m integration.

These hit the public MouseMine InterMine web service, whose servers are known to
be slow (see ``MouseMineConfig.rate_limit_per_s``). When that endpoint is
unreachable or temporarily down the client raises ``ServiceUnavailableError`` /
``RateLimitError``; that is an absent external precondition, not a contract
regression, so we skip (mirroring ``test_live.py`` skipping on a missing index)
rather than fail. A genuine contract break (wrong symbol, missing ortholog)
still surfaces as a real assertion failure because only the availability errors
are converted to skips.
"""

from __future__ import annotations

import pytest

from mgi_link.config import MouseMineConfig
from mgi_link.exceptions import RateLimitError, ServiceUnavailableError

pytestmark = pytest.mark.integration


def test_live_get_marker_wt1() -> None:
    from mgi_link.api.mousemine import MouseMineClient

    client = MouseMineClient(MouseMineConfig())
    try:
        marker = client.get_marker("MGI:98968")
    except (ServiceUnavailableError, RateLimitError) as exc:
        pytest.skip(f"Live MouseMine endpoint unavailable: {exc}")
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
    except (ServiceUnavailableError, RateLimitError) as exc:
        pytest.skip(f"Live MouseMine endpoint unavailable: {exc}")
    finally:
        client.close()
    assert "MGI:98968" in ids
