"""MGI identifier helpers: normalize ``MGI:NNNN`` / ``MP:NNNNNNN`` forms.

Centralising the ``MGI:`` / ``MP:`` strip-and-re-add means callers never parse
identifiers themselves.
"""

from __future__ import annotations

import re

_MGI_ID_RE = re.compile(r"^MGI:(\d+)$", re.IGNORECASE)
_BARE_ID_RE = re.compile(r"^\d+$")
_MP_ID_RE = re.compile(r"^MP:(\d{7})$", re.IGNORECASE)
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._<>()@/+-]{0,127}$")

# External-identifier shapes recognised so resolvers can redirect to the xref index.
_ENSMUSG_RE = re.compile(r"^ENSMUSG\d{6,}", re.IGNORECASE)
_ENSG_RE = re.compile(r"^ENSG\d{6,}", re.IGNORECASE)
_HGNC_RE = re.compile(r"^HGNC:\d+$", re.IGNORECASE)


def normalize_mgi_id(value: str) -> str | None:
    """Return the canonical ``MGI:NNNN`` form for an id, or ``None`` if not one.

    Accepts ``MGI:98968``, ``mgi:98968``, and the bare numeric ``98968`` forms.
    """
    text = (value or "").strip()
    match = _MGI_ID_RE.match(text)
    if match:
        return f"MGI:{match.group(1)}"
    if _BARE_ID_RE.match(text):
        return f"MGI:{text}"
    return None


def looks_like_mgi_id(value: str) -> bool:
    """True when ``value`` is an MGI id in either accepted form."""
    return normalize_mgi_id(value) is not None


def normalize_mp_id(value: str) -> str | None:
    """Return the canonical ``MP:NNNNNNN`` form for an id, or ``None``."""
    text = (value or "").strip()
    match = _MP_ID_RE.match(text)
    if match:
        return f"MP:{match.group(1)}"
    return None


def looks_like_mp_id(value: str) -> bool:
    """True when ``value`` is an MP term id."""
    return normalize_mp_id(value) is not None


def looks_like_symbol(value: str) -> bool:
    """True for a plausible marker-symbol shape (and not an MGI/MP id)."""
    text = (value or "").strip()
    if not text or looks_like_mgi_id(text) or looks_like_mp_id(text):
        return False
    return bool(_SYMBOL_RE.match(text))


def infer_xref_source(value: str) -> str | None:
    """Map an external-id-shaped string to an xref source, or ``None``.

    Lets a symbol-resolution miss redirect the caller to the xref index
    (e.g. an Ensembl mouse gene id thrown at ``resolve_marker``).
    """
    text = (value or "").strip()
    if _ENSMUSG_RE.match(text) or _ENSG_RE.match(text):
        return "ensembl_gene_id"
    if _HGNC_RE.match(text):
        return "hgnc_id"
    return None
