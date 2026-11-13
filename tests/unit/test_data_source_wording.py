"""Agent-facing text must describe how the container really gets its data."""

from __future__ import annotations

from mgi_link.mcp.capabilities import build_capabilities
from mgi_link.mcp.resources import MGI_REFERENCE_NOTES, MGI_SERVER_INSTRUCTIONS


def test_agent_text_describes_the_pinned_release_not_cron() -> None:
    surfaces = [
        str(build_capabilities()["data_source"]),
        MGI_SERVER_INSTRUCTIONS,
        MGI_REFERENCE_NOTES,
    ]
    for text in surfaces:
        assert "cron" not in text.lower()
    assert "pinned" in str(build_capabilities()["data_source"])
