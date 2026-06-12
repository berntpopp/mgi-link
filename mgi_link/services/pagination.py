"""Uniform truncation contract for list-returning tools.

Every list tool returns ``total`` (matches before the cap), ``returned`` (rows in
this payload), ``limit`` (cap applied), and ``truncated`` (``total > returned``) so
an LLM can never mistake a capped list for a complete one.
"""

from __future__ import annotations


def page_fields(*, total: int, returned: int, limit: int) -> dict[str, int | bool]:
    """Return the canonical truncation block."""
    return {
        "total": total,
        "returned": returned,
        "limit": limit,
        "truncated": total > returned,
    }
