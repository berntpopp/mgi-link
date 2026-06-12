"""Unit tests for argument ergonomics (aliases, did-you-mean, signatures)."""

from __future__ import annotations

from mgi_link.mcp.arg_help import (
    describe_constraints,
    did_you_mean,
    normalize_alias_args,
    tool_signature,
)


def test_normalize_alias_args_rewrites_known_alias() -> None:
    args, applied = normalize_alias_args(["query"], {"symbol": "Wt1"})
    assert args == {"query": "Wt1"}
    assert applied == [("symbol", "query")]


def test_normalize_alias_args_explicit_canonical_wins() -> None:
    args, applied = normalize_alias_args(["query"], {"query": "Wt1", "symbol": "Pax6"})
    assert args == {"query": "Wt1"}
    assert applied == []


def test_normalize_alias_args_ignores_alias_when_canonical_not_a_param() -> None:
    # 'system' -> 'mp_system'; if the tool has no mp_system param, leave untouched.
    args, applied = normalize_alias_args(["query"], {"system": "renal"})
    assert args == {"system": "renal"}
    assert applied == []


def test_did_you_mean() -> None:
    assert did_you_mean("symbol", ["query"]) == "query"
    assert did_you_mean("queryy", ["query"]) == "query"
    assert did_you_mean("zzzzz", ["query"]) is None


def test_describe_constraints_enum() -> None:
    allowed, human = describe_constraints({"enum": ["a", "b"]})
    assert allowed == ["a", "b"]
    assert "one of" in human


def test_describe_constraints_range() -> None:
    allowed, human = describe_constraints({"minimum": 1, "maximum": 200})
    assert allowed == ["1..200"]
    assert "between" in human


def test_describe_constraints_none() -> None:
    assert describe_constraints({"type": "string"}) is None


def test_tool_signature() -> None:
    schema = {"properties": {"query": {}, "response_mode": {}}, "required": ["query"]}
    assert tool_signature("get_marker", schema) == "get_marker(query, response_mode=)"
