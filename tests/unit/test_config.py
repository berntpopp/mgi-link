"""Tests for mgi_link.config defaults and invariants."""

from __future__ import annotations


def test_mousemine_defaults_off() -> None:
    from mgi_link.config import MouseMineConfig

    cfg = MouseMineConfig()
    assert cfg.enable_live_fallback is False
    assert cfg.user_agent.startswith("mgi-link/")
