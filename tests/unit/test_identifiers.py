"""Unit tests for MGI/MP identifier helpers."""

from __future__ import annotations

import pytest

from mgi_link.identifiers import (
    infer_xref_source,
    looks_like_mgi_id,
    looks_like_mp_id,
    looks_like_symbol,
    normalize_mgi_id,
    normalize_mp_id,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("MGI:98968", "MGI:98968"),
        ("mgi:98968", "MGI:98968"),
        ("98968", "MGI:98968"),
        ("  98968 ", "MGI:98968"),
        ("Wt1", None),
        ("MP:0005367", None),
        ("", None),
    ],
)
def test_normalize_mgi_id(value: str, expected: str | None) -> None:
    assert normalize_mgi_id(value) == expected


def test_looks_like_mgi_id() -> None:
    assert looks_like_mgi_id("MGI:1") is True
    assert looks_like_mgi_id("123") is True
    assert looks_like_mgi_id("Wt1") is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [("MP:0005367", "MP:0005367"), ("mp:0000001", "MP:0000001"), ("MP:123", None), ("Wt1", None)],
)
def test_normalize_mp_id(value: str, expected: str | None) -> None:
    assert normalize_mp_id(value) == expected
    assert looks_like_mp_id(value) is (expected is not None)


def test_looks_like_symbol() -> None:
    assert looks_like_symbol("Wt1") is True
    assert looks_like_symbol("Wt1<tm1Jae>") is True
    assert looks_like_symbol("MGI:98968") is False
    assert looks_like_symbol("MP:0005367") is False
    assert looks_like_symbol("") is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ENSMUSG00000016458", "ensembl_gene_id"),
        ("ENSG00000184937", "ensembl_gene_id"),
        ("HGNC:12796", "hgnc_id"),
        ("Wt1", None),
    ],
)
def test_infer_xref_source(value: str, expected: str | None) -> None:
    assert infer_xref_source(value) == expected
