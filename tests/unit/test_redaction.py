"""Guard: URL redaction strips credentials/tokens before logging or echoing.

A configured endpoint URL can carry secrets in its userinfo, query, or
fragment. Those must never reach logs or a diagnostics payload.
"""

from __future__ import annotations

import pytest

from mgi_link.redaction import redact_url

_SECRET_URL = "https://user:pass@example.test?token=x"  # noqa: S105 - test fixture, not a secret


def test_redact_strips_userinfo_query_and_fragment() -> None:
    assert redact_url(_SECRET_URL) == "https://example.test"


def test_redact_leaks_no_secret_substring() -> None:
    redacted = redact_url("https://user:pass@example.test/path?token=x#frag")
    for secret in ("user", "pass", "token", "frag"):
        assert secret not in redacted


def test_redact_preserves_host_port_and_path() -> None:
    assert redact_url("http://svc.internal:8080/mousemine/service") == (
        "http://svc.internal:8080/mousemine/service"
    )


def test_redact_plain_url_is_unchanged() -> None:
    url = "https://www.mousemine.org/mousemine/service"
    assert redact_url(url) == url


@pytest.mark.parametrize("bad", ["", "not a url", "://nohost"])
def test_redact_tolerates_malformed_input(bad: str) -> None:
    # Never raises; never echoes back embedded secrets.
    redact_url(bad)
