"""Redaction helpers for values that may carry secrets before they are logged.

A configured endpoint URL can embed credentials (``user:pass@``), an API token
in the query string, or a fragment. ``redact_url`` reduces a URL to its safe,
non-identifying parts (scheme, host, port, path) so it can be logged or echoed
in a diagnostics payload without leaking secrets.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Return ``url`` with any userinfo, query, and fragment removed.

    Keeps scheme, host, port, and path; drops the parts that can carry secrets.
    Never raises: a value that cannot be parsed as a URL is reported as
    ``"<redacted>"`` rather than echoed back.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<redacted>"
    if not parts.scheme or not parts.hostname:
        return "<redacted>"
    netloc = parts.hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
