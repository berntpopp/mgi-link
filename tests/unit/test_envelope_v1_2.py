"""Response-Envelope Standard v1.2: provenance on every success, checked against the schema.

The schema is vendored from berntpopp/genefoundry-envelope, tag v1.2.0. Every data tool
runs in-process against the fixture index.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from mgi_link.mcp.capabilities import TOOLS

CONFORMANCE = Path(__file__).parents[1] / "conformance"
SCHEMA = Draft202012Validator(json.loads((CONFORMANCE / "envelope-v1.2.schema.json").read_text()))
#: One successful call per data tool, answered by the fixture index.
DATA_CALLS: dict[str, dict[str, Any]] = {
    "resolve_marker": {"query": "Wt1"},
    "get_marker": {"query": "Wt1"},
    "search_markers": {"query": "Wt1"},
    "get_marker_alleles": {"query": "Wt1"},
    "get_marker_phenotypes": {"query": "Wt1"},
    "get_phenotype_overview": {"query": "Wt1"},
    "get_marker_diseases": {"query": "Wt1"},
    "get_marker_ortholog": {"query": "Wt1"},
    "get_mp_term": {"mp_id": "MP:0005367"},
    "search_phenotype_terms": {"query": "renal"},
    "find_markers_by_phenotype": {"mp_id": "MP:0005367"},
}
OPS_TOOLS = {"get_server_capabilities", "get_diagnostics"}  # outside the v1.2 rule


def _errors(envelope: Any) -> list[str]:
    return [f"{e.json_path}: {e.message}" for e in SCHEMA.iter_errors(envelope)]


def test_vendored_schema_is_the_v1_2_0_release() -> None:
    digest = hashlib.sha256((CONFORMANCE / "envelope-v1.2.schema.json").read_bytes()).hexdigest()
    assert digest == (CONFORMANCE / "envelope-v1.2.schema.sha256").read_text().strip()
    assert digest == "c3c47e20d7dd189aac2568fc963b5514d7a5ac2c3e5f21d126f42c96d1ad1ae3"


def test_every_data_tool_has_a_call() -> None:
    assert set(DATA_CALLS) == set(TOOLS) - OPS_TOOLS


@pytest.mark.parametrize("tool", DATA_CALLS)
async def test_data_tool_success_is_a_v1_2_envelope(
    tool: str, facade: Any, structured: Any, repo: Any
) -> None:
    envelope = structured(await facade.call_tool(tool, DATA_CALLS[tool]))

    assert envelope["success"] is True, envelope
    assert _errors(envelope) == []
    index = repo.get_meta()
    meta = envelope["_meta"]
    # The release and the build time of the index that answered, not of this call.
    assert (meta["source"], meta["data_version"]) == ("mgi", index["release"])
    assert meta["retrieved_at"] == index["build_utc"][:19] + "Z"
    assert all(meta[key] for key in ("source", "data_version", "retrieved_at"))


async def test_live_fallback_names_mousemine_and_is_dated_to_the_call(
    fallback_facade: Any, structured: Any
) -> None:
    envelope = structured(await fallback_facade.call_tool("resolve_marker", {"query": "Wt1"}))

    assert _errors(envelope) == []
    meta = envelope["_meta"]
    assert (meta["source"], meta["data_version"]) == ("mousemine", "live")
    assert meta["retrieved_at"].endswith("Z")


async def test_error_is_a_valid_envelope_without_provenance(facade: Any, structured: Any) -> None:
    for arguments in ({"query": "Zzzznotreal"}, {"queryy": "Wt1"}):  # not found, bad argument
        envelope = structured(await facade.call_tool("get_marker", arguments))
        assert envelope["success"] is False
        assert _errors(envelope) == []
        assert "retrieved_at" not in envelope["_meta"]
