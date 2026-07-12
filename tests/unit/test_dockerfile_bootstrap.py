"""Supply-chain guard: the builder must bootstrap ``uv`` from a digest-pinned
image via ``COPY --from``, never a floating ``pip install --upgrade pip uv``.
A floating installer resolves the latest PyPI ``uv``/``pip`` at build time,
which is an unpinned, mutable dependency in the image build path.
Research use only; not clinical decision support."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Digest-pinned uv builder image (fleet standard, F-19).
UV_PINNED = (
    "ghcr.io/astral-sh/uv:0.8.7@sha256:"
    "1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab"
)


def test_dockerfile_pins_uv_and_has_no_floating_pip_upgrade() -> None:
    text = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install --upgrade" not in text, "floating pip/uv upgrade must be removed"
    assert UV_PINNED in text, "uv must be bootstrapped from the digest-pinned image via COPY --from"
