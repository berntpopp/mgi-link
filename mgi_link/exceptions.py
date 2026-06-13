"""Custom exceptions for mgi-link.

Two error families flow into the MCP envelope:

- **Data-store errors** raised by the local SQLite repository / services
  (``NotFoundError``, ``WithdrawnEntryError``, ``AmbiguousQueryError``,
  ``DataUnavailableError``).
- **Live-fallback errors** raised by the optional MouseMine client when the
  local DB is unavailable (``RateLimitError``, ``ServiceUnavailableError``).

``run_mcp_tool`` classifies each into a stable ``error_code`` (see
``mgi_link.mcp.envelope``).
"""

from __future__ import annotations


class MgiError(Exception):
    """Base exception for all mgi-link data/client errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Store a human-readable message and optional HTTP status code."""
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        """Return the message (with status code when present)."""
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class InvalidInputError(MgiError):
    """A tool/service argument failed validation before any lookup ran."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        *,
        allowed: list[str] | None = None,
        hint: str | None = None,
    ) -> None:
        """Initialise with the offending field and optional recovery data.

        ``allowed`` and ``hint`` are surfaced as structured top-level keys on the
        error envelope (``allowed_values``/``hint``) so a consumer never has to
        parse them out of a (length-capped) message.
        """
        super().__init__(message)
        self.field = field
        self.allowed = allowed
        self.hint = hint


class NotFoundError(MgiError):
    """A lookup returned no rows for an otherwise valid identifier."""

    def __init__(self, message: str = "No matching MGI record found.") -> None:
        """Initialise with a 404 status code."""
        super().__init__(message, status_code=404)


class WithdrawnEntryError(NotFoundError):
    """The marker/ID exists in MGI but is withdrawn, split, or merged.

    Subclasses :class:`NotFoundError` so it classifies as ``not_found`` in the
    error envelope, but carries the withdrawn symbol/ID, the withdrawal status,
    and any replacement records so the envelope can flag ``obsolete: true`` and
    chain to the successor(s).
    """

    def __init__(
        self,
        withdrawn: str,
        *,
        status: str,
        replaced_by: list[dict[str, str]] | None = None,
        message: str | None = None,
    ) -> None:
        """Store the withdrawn symbol/ID, its status, and replacement record(s)."""
        self.withdrawn = withdrawn
        self.withdrawn_status = status
        self.replaced_by = replaced_by or []
        if message is None:
            if self.replaced_by:
                targets = ", ".join(
                    f"{r.get('symbol', '?')} ({r.get('mgi_id', '?')})" for r in self.replaced_by
                )
                message = f"{withdrawn} was withdrawn from MGI ({status}). See: {targets}."
            else:
                message = f"{withdrawn} was withdrawn from MGI ({status}) and has no replacement."
        super().__init__(message)


class AmbiguousQueryError(MgiError):
    """A query matched several records and cannot be resolved unambiguously."""

    def __init__(self, message: str, *, candidates: list[dict[str, str]] | None = None) -> None:
        """Store the ambiguous candidates so the envelope can surface them."""
        super().__init__(message)
        self.candidates = candidates or []


class DataUnavailableError(MgiError):
    """The local MGI SQLite index is missing, unbuilt, or unreadable."""

    def __init__(self, message: str = "The local MGI database is not available.") -> None:
        """Initialise with a 503 status code."""
        super().__init__(message, status_code=503)


class RateLimitError(MgiError):
    """The live MouseMine endpoint signalled rate limiting (HTTP 429)."""

    def __init__(self, message: str = "MouseMine API rate limit hit.") -> None:
        """Initialise with a 429 status code."""
        super().__init__(message, status_code=429)


class ServiceUnavailableError(MgiError):
    """The live MouseMine endpoint is temporarily unavailable (5xx / network error)."""

    def __init__(self, message: str = "MouseMine API is temporarily unavailable.") -> None:
        """Initialise with a 503 status code."""
        super().__init__(message, status_code=503)


class DownloadError(MgiError):
    """A bulk-download attempt failed (network/HTTP error)."""
