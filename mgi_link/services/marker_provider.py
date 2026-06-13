"""Structural interface for marker resolution sources.

Both the offline ``MgiRepository`` and the live ``MouseMineClient`` satisfy this
Protocol, so ``MgiService.resolve``/``get_marker`` run unchanged against whichever
provider is live. Method names and parameter names mirror ``MgiRepository`` exactly
so the repository satisfies the Protocol structurally under mypy strict.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MarkerProvider(Protocol):
    """The four lookups the resolution cascade depends on."""

    def get_marker(self, mgi_id: str) -> dict[str, Any] | None: ...

    def lookup_symbol(self, symbol: str) -> list[tuple[str, str]]: ...

    def lookup_by_xref(self, source: str, value: str) -> list[str]: ...

    def get_ortholog(self, mgi_id: str) -> dict[str, Any] | None: ...
