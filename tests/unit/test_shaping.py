"""Unit tests for response_mode projection."""

from __future__ import annotations

from mgi_link.services import shaping


def test_shape_resolution_modes() -> None:
    record = {
        "query": "Wt1",
        "mgi_id": "MGI:1",
        "symbol": "Wt1",
        "match_type": "current",
        "name": "x",
    }
    assert set(shaping.shape_resolution(record, "minimal")) == {
        "query",
        "mgi_id",
        "symbol",
        "match_type",
    }
    assert shaping.shape_resolution(record, "full") == record
    compact = shaping.shape_resolution({**record, "name": None}, "compact")
    assert "name" not in compact


def test_shape_marker_modes() -> None:
    record = {
        "mgi_id": "MGI:1",
        "symbol": "Wt1",
        "name": "x",
        "marker_type": "Gene",
        "cm_position": "105",
        "status": "O",
        "synonyms": [],
    }
    minimal = shaping.shape_marker(record, "minimal")
    assert "cm_position" not in minimal and "mgi_id" in minimal
    compact = shaping.shape_marker(record, "compact")
    assert "cm_position" not in compact  # dropped verbose
    assert "synonyms" not in compact  # empty dropped
    assert shaping.shape_marker(record, "standard") == record


def test_shape_summary_and_allele() -> None:
    summary = {"mgi_id": "MGI:1", "symbol": "Wt1", "name": None}
    assert "name" not in shaping.shape_summary(summary, "compact")
    assert set(shaping.shape_summary(summary, "minimal")) <= {
        "mgi_id",
        "symbol",
        "match_type",
        "symbol_type",
    }
    allele = {
        "allele_id": "MGI:2",
        "symbol": "Wt1<tm1>",
        "allele_type": "Targeted",
        "attributes": [],
    }
    assert set(shaping.shape_allele(allele, "minimal")) == {"allele_id", "symbol", "allele_type"}
    assert "attributes" not in shaping.shape_allele(allele, "compact")
