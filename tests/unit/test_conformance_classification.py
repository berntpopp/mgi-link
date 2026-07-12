"""Classification guards for opt-in live conformance probes."""

from __future__ import annotations

import pytest

from tests.conformance.test_transport_v1 import test_mcp_transport_standard_v1


def test_mcp_transport_probe_is_an_integration_test() -> None:
    """A probe that opens a TCP connection must bypass the unit network deny fixture."""
    markers = getattr(test_mcp_transport_standard_v1, "pytestmark", [])
    assert any(marker.name == "integration" for marker in markers)


def test_unit_socket_connection_is_blocked() -> None:
    """The default unit-test suite must retain its outbound-network boundary."""
    import socket

    with pytest.raises(AssertionError, match="unit tests must mock outbound network access"):
        socket.create_connection(("127.0.0.1", 9))
