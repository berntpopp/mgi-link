"""Unit tests for the truncation-contract helper."""

from __future__ import annotations

from mgi_link.services.pagination import page_fields


def test_page_fields_truncated() -> None:
    assert page_fields(total=126, returned=100, limit=100) == {
        "total": 126,
        "returned": 100,
        "limit": 100,
        "truncated": True,
    }


def test_page_fields_complete() -> None:
    out = page_fields(total=5, returned=5, limit=200)
    assert out["truncated"] is False
    assert out["total"] == 5
