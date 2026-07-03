"""mgi-link: an MCP/API server grounding mouse genetics in the MGI dataset."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mgi-link")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
