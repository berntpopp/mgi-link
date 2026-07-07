"""Tests for mgi_link.config defaults and invariants."""

from __future__ import annotations


def test_mousemine_defaults_off() -> None:
    from mgi_link.config import MouseMineConfig

    cfg = MouseMineConfig()
    assert cfg.enable_live_fallback is False
    assert cfg.user_agent.startswith("mgi-link/")


def test_mousemine_default_user_agent_has_no_personal_contact() -> None:
    """The default outbound User-Agent must not leak a personal email."""
    from mgi_link.config import PROJECT_CONTACT_URL, MouseMineConfig

    cfg = MouseMineConfig()
    assert cfg.contact_email == ""
    ua = cfg.user_agent
    assert "@" not in ua  # no mailto / email of any kind by default
    assert "charite" not in ua
    assert PROJECT_CONTACT_URL in ua


def test_mousemine_user_agent_uses_configured_contact() -> None:
    """An operator may still opt into a monitored contact mailbox."""
    from mgi_link import __version__
    from mgi_link.config import MouseMineConfig

    cfg = MouseMineConfig(contact_email="ops@example.test")
    assert cfg.user_agent == f"mgi-link/{__version__} (mailto:ops@example.test)"


def test_data_default_user_agent_has_no_personal_contact() -> None:
    """The reports-download User-Agent must not leak a personal email either."""
    from mgi_link.config import MgiDataConfig

    ua = MgiDataConfig().user_agent
    assert "@" not in ua
    assert "charite" not in ua
