"""Closed-vocabulary filter validation and the phenotype-scope flag.

Split out of ``mgi_service.py`` (per-file line budget). These helpers reject an
unrecognised ``marker_type``/``allele_type`` with ``invalid_input`` -- naming the
full server-controlled vocabulary -- instead of letting it silently match nothing
(the silent-empty-filter class, issue #28), and stamp the explicit single-locus
scope on every phenotype response.
"""

from __future__ import annotations

from typing import Any

from mgi_link.constants import (
    ALLELE_TYPE_ALIASES,
    ALLELE_TYPES,
    MARKER_TYPES,
    MP_TOP_SYSTEM_NAMES,
    PHENOTYPE_SCOPE,
    PHENOTYPE_SCOPE_NOTE,
)
from mgi_link.exceptions import InvalidInputError

__all__ = [
    "PHENOTYPE_SCOPE",
    "canonical_allele_type",
    "canonical_marker_type",
    "safe_top_system_names",
    "scope_fields",
]


def safe_top_system_names(systems: list[dict[str, str]]) -> list[str]:
    """Top-level MP system names safe to surface in an error's allowed_values.

    The live grid is built from the downloaded MP OBO (EXTERNAL data), so a name is
    emitted ONLY if it is a member of the curated server-controlled allowlist
    ``MP_TOP_SYSTEM_NAMES`` — an ontology-injected label can never reach the caller.
    Order is preserved (display_order from the grid).
    """
    return [s["name"] for s in systems if s.get("name") in MP_TOP_SYSTEM_NAMES]


def scope_fields() -> dict[str, Any]:
    """The explicit phenotype-scope flag stamped on every phenotype response.

    Makes a zero/partial count self-describing: MGI_GenePheno excludes
    conditional/Cre-driven and multi-genic genotypes, so an empty result is scoped,
    NOT authoritative (issue #28, defect D1).
    """
    return {
        "scope": PHENOTYPE_SCOPE,
        "excludes_conditional_genotypes": True,
        "scope_note": PHENOTYPE_SCOPE_NOTE,
    }


def canonical_allele_type(allele_type: str | None) -> str | None:
    """Map a friendly allele-type token to its canonical filter substring, or raise.

    Empty means "no filter". An alias resolves to its canonical type; a raw value is
    accepted only if it substring-matches at least one canonical ``ALLELE_TYPE``
    (case-insensitive) -- the same match the LIKE filter applies. An UNRECOGNISED
    value is REJECTED with invalid_input, never silently matched to nothing.
    """
    if not allele_type:
        return None
    raw = allele_type.strip()
    token = ALLELE_TYPE_ALIASES.get(raw.lower(), raw)
    if token and any(token.lower() in canonical.lower() for canonical in ALLELE_TYPES):
        return token
    raise InvalidInputError(
        f"Unknown allele_type '{raw}'.",
        field="allele_type",
        allowed=list(ALLELE_TYPES),
        hint="Use a generation-method type (e.g. 'Targeted', 'knockout', 'crispr').",
        allowed_trusted=True,
    )


def canonical_marker_type(marker_type: str | None) -> str | None:
    """Return the canonical MARKER_TYPES value (case-insensitive), or raise.

    The search filter is an EXACT match, so an unrecognised/wrong-case value would
    silently match nothing; resolve to the canonical spelling and reject anything
    outside the closed vocabulary with invalid_input.
    """
    if not marker_type:
        return None
    raw = marker_type.strip()
    for canonical in MARKER_TYPES:
        if raw.lower() == canonical.lower():
            return canonical
    raise InvalidInputError(
        f"Unknown marker_type '{raw}'.",
        field="marker_type",
        allowed=list(MARKER_TYPES),
        hint="Use a marker type (e.g. 'Gene', 'Pseudogene', 'QTL', 'Transgene').",
        allowed_trusted=True,
    )
