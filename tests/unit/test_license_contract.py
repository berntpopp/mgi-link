"""Contract-Truth: every served licence surface matches the verified MGI terms."""

from __future__ import annotations

import json
from pathlib import Path

from mgi_link.constants import MGI_LICENSE
from mgi_link.mcp.capabilities import build_capabilities
from mgi_link.mcp.resources import MGI_REFERENCE_NOTES

ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION = json.loads((ROOT / "release" / "data-authorization.json").read_text())


def test_served_license_matches_the_recorded_data_authorization() -> None:
    license_ = AUTHORIZATION["license"]
    assert license_["spdx"] == "CC-BY-4.0"
    for fact in ("CC BY 4.0", license_["url"], license_["terms_url"], "Images"):
        assert fact in MGI_LICENSE
    # MGI's own attribution template (mgihome/other/citation.shtml).
    assert "Mouse Genome Database (MGD) at the Mouse Genome Informatics website" in MGI_LICENSE
    assert "freely available" not in MGI_LICENSE


def test_every_license_surface_serves_the_single_source() -> None:
    assert build_capabilities()["license"] == MGI_LICENSE
    assert MGI_LICENSE in MGI_REFERENCE_NOTES
    for doc in ("README.md", "docs/data.md"):
        text = (ROOT / doc).read_text()
        assert "CC BY 4.0" in text
        assert "free for\nresearch use" not in text and "freely available" not in text
