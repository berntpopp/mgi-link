"""Unit contract for the error-message sanitize primitive.

``sanitize_message`` strips the untrusted-text fence's forbidden control/
zero-width/bidi/NUL code points from any caller-visible message/error string and
length-caps it. It deliberately does NOT rewrite injection prose (that is severed
at the source for attacker-influenceable strings); this test pins only the
code-point + length behaviour it IS responsible for.
"""

from __future__ import annotations

from mgi_link.mcp.untrusted_content import (
    FORBIDDEN_CODEPOINTS,
    MAX_MESSAGE_CHARS,
    sanitize_message,
)


def test_strips_nul_zwj_bom_and_bidi_override() -> None:
    dirty = "boom\x00 mid‍ end﻿ tail‮."
    clean = sanitize_message(dirty)
    for ch in ("\x00", "‍", "﻿", "‮"):
        assert ch not in clean, f"forbidden codepoint U+{ord(ch):04X} not stripped"
    # ordinary prose survives verbatim (only code points are removed)
    assert clean == "boom mid end tail."


def test_preserves_ordinary_prose_and_scientific_symbols() -> None:
    text = "MouseMine rejected the request \u0394G = \u22121.2 kcal/mol\tp.Gly12Asp"
    assert sanitize_message(text) == text


def test_length_capped_at_max_message_chars() -> None:
    assert len(sanitize_message("a" * 5000)) == MAX_MESSAGE_CHARS
    assert MAX_MESSAGE_CHARS == 280


def test_every_forbidden_codepoint_is_removed() -> None:
    dirty = "x".join(chr(cp) for cp in sorted(FORBIDDEN_CODEPOINTS))
    clean = sanitize_message(dirty)
    assert all(ord(ch) not in FORBIDDEN_CODEPOINTS for ch in clean)
