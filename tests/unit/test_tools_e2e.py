"""End-to-end tests through the real FastMCP facade (envelope contract)."""

from __future__ import annotations

from typing import Any

import pytest

from mgi_link.mcp.capabilities import TOOLS

pytestmark = pytest.mark.mcp


async def test_resolve_marker_success(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("resolve_marker", {"query": "Wt1"}))
    assert payload["success"] is True
    assert payload["mgi_id"] == "MGI:98968"
    assert payload["match_type"] == "current"
    assert payload["_meta"]["tool"] == "resolve_marker"
    assert payload["_meta"]["next_commands"][0]["tool"] == "get_marker"


async def test_get_marker_next_commands(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_marker", {"query": "MGI:98968"}))
    tools = {c["tool"] for c in payload["_meta"]["next_commands"]}
    assert "get_marker_alleles" in tools
    assert "get_phenotype_overview" in tools


async def test_alleles_category_counts(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_marker_alleles", {"query": "Wt1"}))
    assert payload["total_alleles"] == 5
    assert payload["category_counts"]["Targeted"] == 2


async def test_phenotype_overview_via_facade(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_phenotype_overview", {"query": "Wt1"}))
    systems = {s["system"] for s in payload["systems"]}
    assert "renal/urinary system phenotype" in systems


async def test_find_markers_by_phenotype(facade: Any, structured: Any) -> None:
    payload = structured(
        await facade.call_tool("find_markers_by_phenotype", {"mp_id": "MP:0005367"})
    )
    assert payload["success"] is True
    assert any(m["mgi_id"] == "MGI:98968" for m in payload["markers"])


async def test_response_mode_minimal_projection(facade: Any, structured: Any) -> None:
    payload = structured(
        await facade.call_tool("resolve_marker", {"query": "Wt1", "response_mode": "minimal"})
    )
    # minimal keeps only identity anchors
    assert set(payload) <= {"query", "mgi_id", "symbol", "match_type", "_meta", "success"}


async def test_not_found_error_envelope(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("resolve_marker", {"query": "Zzzznotreal"}))
    assert payload["success"] is False
    assert payload["error_code"] == "not_found"
    assert payload["recovery_action"] == "reformulate_input"
    assert payload["_meta"]["next_commands"]  # always present on error


async def test_invalid_mp_id_error(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_mp_term", {"mp_id": "not-an-mp-id"}))
    assert payload["success"] is False
    assert payload["error_code"] == "invalid_input"
    assert payload["field"] == "mp_id"


async def test_argument_alias_rewrite(facade: Any, structured: Any) -> None:
    # 'symbol' is an alias for 'query'
    payload = structured(await facade.call_tool("get_marker", {"symbol": "Wt1"}))
    assert payload["success"] is True
    assert payload["mgi_id"] == "MGI:98968"


async def test_unknown_argument_did_you_mean(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_marker", {"queryy": "Wt1"}))
    assert payload["success"] is False
    assert payload["error_code"] == "invalid_input"
    assert "query" in payload["allowed_values"]


async def test_capabilities_documents_new_contracts(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_server_capabilities", {"detail": "full"}))
    assert "truncation_contract" in payload
    assert "response_mode_semantics" in payload
    assert "behavioral_defaults" in payload
    assert "field_glossary" in payload


async def test_capabilities_lists_all_tools(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_server_capabilities", {}))
    assert payload["tool_count"] == len(TOOLS)
    registered = {t.name for t in await facade.list_tools()}
    assert set(TOOLS) == registered


async def test_ambiguous_query_envelope(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("resolve_marker", {"query": "Dup1"}))
    assert payload["success"] is False
    assert payload["error_code"] == "ambiguous_query"
    assert len(payload["candidates"]) >= 2
    assert payload["_meta"]["next_commands"][0]["tool"] == "get_marker"


async def test_diagnostics_tool(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_diagnostics", {}))
    assert payload["data_available"] is True
    assert payload["marker_count"] == 4


async def test_elapsed_ms_present(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("resolve_marker", {"query": "Wt1"}))
    assert isinstance(payload["_meta"]["elapsed_ms"], int)
    assert payload["_meta"]["elapsed_ms"] >= 0
    err = structured(await facade.call_tool("resolve_marker", {"query": "Zzzznotreal"}))
    assert isinstance(err["_meta"]["elapsed_ms"], int)


async def test_diagnostics_has_build(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_diagnostics", {}))
    assert "version" in payload["build"]
    assert "git_sha" in payload["build"]


async def test_resolve_marker_live_source_in_meta(fallback_facade: Any, structured: Any) -> None:
    payload = structured(await fallback_facade.call_tool("resolve_marker", {"query": "Wt1"}))
    assert payload["_meta"]["source"] == "mousemine"
    assert "source" not in payload


async def test_get_marker_live_source_in_meta_not_body(
    fallback_facade: Any, structured: Any
) -> None:
    payload = structured(await fallback_facade.call_tool("get_marker", {"query": "Wt1"}))
    assert payload["_meta"]["source"] == "mousemine"
    assert payload["_meta"]["partial"] is True
    assert "source" not in payload  # lifted out of the answer body
    assert "partial" not in payload
    tools = [c["tool"] for c in payload["_meta"]["next_commands"]]
    assert "get_marker_alleles" not in tools


async def test_resolve_index_has_no_source(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("resolve_marker", {"query": "Wt1"}))
    assert "source" not in payload["_meta"]


async def test_diagnostics_reports_live_fallback(facade: Any, structured: Any) -> None:
    payload = structured(await facade.call_tool("get_diagnostics", {}))
    assert "live_fallback" in payload
    assert "enabled" in payload["live_fallback"]
    assert "base_url" in payload["live_fallback"]
    assert payload["live_fallback"]["enabled"] is False


async def test_diagnostics_redacts_base_url_secrets(
    facade: Any, structured: Any, monkeypatch: Any
) -> None:
    """A credential-bearing MouseMine URL must never surface in diagnostics."""
    from mgi_link.config import settings

    monkeypatch.setattr(settings.mousemine, "base_url", "https://user:pass@mm.internal?token=x")
    payload = structured(await facade.call_tool("get_diagnostics", {}))
    base_url = payload["live_fallback"]["base_url"]
    for secret in ("user", "pass", "token"):
        assert secret not in base_url
    assert base_url == "https://mm.internal"


async def test_identity_tools_data_unavailable_when_cold_no_fallback(
    cold_facade: Any, structured: Any
) -> None:
    """Both identity tools must return data_unavailable when there is no repo and no fallback."""
    for tool in ("resolve_marker", "get_marker"):
        payload = structured(await cold_facade.call_tool(tool, {"query": "Wt1"}))
        assert payload["success"] is False
        assert payload["error_code"] == "data_unavailable"
