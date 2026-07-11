"""MCP envelope boundary: success/_meta injection and structured errors.

Tools return a plain dict; :func:`run_mcp_tool` injects ``success`` and ``_meta``
on success, and converts any exception into a structured error dict (returned,
never raised) so the LLM sees a typed failure rather than an opaque masked
message.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from mgi_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    DownloadError,
    InvalidInputError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    WithdrawnEntryError,
)
from mgi_link.identifiers import looks_like_symbol
from mgi_link.mcp.next_commands import cmd, default_error_next_commands, withdrawn_recovery
from mgi_link.mcp.untrusted_content import (
    UntrustedTextLimitError,
    sanitize_message,
    strip_forbidden_codepoints,
)

logger = logging.getLogger(__name__)

# Per-call _meta is kept lean: static provenance (citation, MGI release) lives
# ONLY in get_server_capabilities. Per-call _meta carries dynamic fields (tool,
# request_id, next_commands) PLUS the research-use disclaimer
# (unsafe_for_clinical_use), which -- per the fleet-wide Response-Envelope
# Standard v1 -- must be repeated on every call, success and error alike, at
# every response_mode. _UNSAFE_FOR_CLINICAL_USE_META is merged in last on every
# envelope-building path so no response_mode projection or field allowlist can
# ever drop it.
_RETRYABLE = {"rate_limited", "upstream_unavailable", "data_unavailable"}
_UNSAFE_FOR_CLINICAL_USE_META: dict[str, Any] = {"unsafe_for_clinical_use": True}


@dataclass
class McpErrorContext:
    """Per-call context so envelopes can name the failing tool and recovery."""

    tool_name: str
    fallback: dict[str, Any] | None = field(default=None)
    arguments: dict[str, Any] = field(default_factory=dict)


class McpToolError(Exception):
    """Raised inside a tool body to emit a specific error code/message."""

    def __init__(self, *, error_code: str, message: str) -> None:
        """Store an error code and client-safe message."""
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _request_id() -> str:
    return uuid.uuid4().hex[:12]


# FIXED, error-code-specific PUBLIC messages. Classified exceptions build their
# text from the caller's query/identifier or an upstream value (see mgi_service
# ``AmbiguousQueryError``/``NotFoundError`` and ``InvalidInputError`` for a raw
# ``mp_system``, plus DataUnavailableError's DB path). Code-point stripping does
# NOT neutralise injection prose, so the public message is NEVER interpolated
# from that text -- the raw detail stays only in the (server-side) chained cause.
# Actionable specifics travel in the structured field/allowed_values/hint/
# candidates fields, which are validated below.
_PUBLIC_MESSAGE: dict[str, str] = {
    "response_limit_exceeded": (
        "The response exceeded the untrusted-text size/count limit. Re-call with a smaller limit."
    ),
    "not_found": "No matching MGI record was found for the request.",
    "ambiguous_query": "The query matched multiple MGI records. See candidates to disambiguate.",
    "invalid_input": "The request arguments were invalid. See field, allowed_values, and hint.",
    "data_unavailable": "The local MGI database is not available.",
    "rate_limited": "MouseMine rate limit hit. Retry shortly.",
    "upstream_unavailable": "The MouseMine upstream is temporarily unavailable.",
    "internal_error": "An internal error occurred. The request was not completed.",
}
_WITHDRAWN_MESSAGE = "The requested MGI record is withdrawn or obsolete. See replaced_by."

_MGI_ID_RE = re.compile(r"^MGI:\d+$")
_STATUS_RE = re.compile(r"^[A-Za-z][A-Za-z _-]{0,63}$")
_SYMBOL_TYPES = frozenset({"current", "synonym"})


def _sanitize_tree(value: Any) -> Any:
    """Recursively code-point-strip every string leaf of an error envelope.

    A whole-envelope backstop (DEEPEST LESSON): the fixed public message and the
    validated identifier fields are the primary defence, but this guarantees no
    forbidden control/zero-width/bidi/NUL code point survives in ANY leaf --
    ``message``, ``field``, ``allowed_values``, ``hint``, ``candidates``, and every
    ``_meta.next_commands[*].arguments.*`` value -- in both response mirrors.
    """
    if isinstance(value, str):
        return strip_forbidden_codepoints(value)
    if isinstance(value, dict):
        return {key: _sanitize_tree(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_sanitize_tree(item) for item in value]
    return value


def _sanitize_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Typed wrapper: run the whole-envelope code-point backstop over an error dict."""
    sanitized = _sanitize_tree(envelope)
    return sanitized if isinstance(sanitized, dict) else envelope


def _valid_records(records: Any) -> list[dict[str, Any]]:
    """Rebuild ``candidates`` / ``replaced_by`` from validated identifier fields only.

    These may originate from the live MouseMine fallback (external data). Each
    output record is reconstructed with ONLY schema-validated identifier leaves
    (``mgi_id``, a well-formed ``symbol``, an enum ``symbol_type``); descriptive
    free-text (``name``, ``marker_type``) is DROPPED because code-point stripping
    would leave injection prose in it. A record whose ``mgi_id`` (or a present
    ``symbol``) does not match its exact grammar is dropped entirely, so a routed
    ``next_commands`` argument can never carry attacker prose.
    """
    out: list[dict[str, Any]] = []
    for rec in records if isinstance(records, list) else []:
        if not isinstance(rec, dict):
            continue
        mgi_id = rec.get("mgi_id")
        if not isinstance(mgi_id, str) or _MGI_ID_RE.match(mgi_id) is None:
            continue
        clean: dict[str, Any] = {"mgi_id": mgi_id}
        symbol = rec.get("symbol")
        if isinstance(symbol, str) and symbol:
            if not looks_like_symbol(symbol):
                continue  # a real marker always has a well-formed symbol; drop prose
            clean["symbol"] = symbol
        if rec.get("symbol_type") in _SYMBOL_TYPES:
            clean["symbol_type"] = rec["symbol_type"]
        out.append(clean)
    return out


def _valid_status(status: Any) -> str | None:
    """Return a withdrawn-status token only if it is a simple word, else ``None``."""
    if isinstance(status, str) and _STATUS_RE.match(status):
        return status
    return None


def _classify(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_code, fixed_public_message)`` for an exception.

    The message is ALWAYS a fixed, server-authored string (never interpolated from
    caller input or upstream data). ``McpToolError`` bodies are the one path whose
    message is authored in-tool; it is length-capped + code-point-stripped.
    """
    if isinstance(exc, McpToolError):
        return exc.error_code, sanitize_message(exc.message)
    if isinstance(exc, UntrustedTextLimitError):
        return "response_limit_exceeded", _PUBLIC_MESSAGE["response_limit_exceeded"]
    if isinstance(exc, WithdrawnEntryError):  # a NotFoundError subclass; check first
        return "not_found", _WITHDRAWN_MESSAGE
    if isinstance(exc, NotFoundError):
        return "not_found", _PUBLIC_MESSAGE["not_found"]
    if isinstance(exc, AmbiguousQueryError):
        return "ambiguous_query", _PUBLIC_MESSAGE["ambiguous_query"]
    if isinstance(exc, InvalidInputError):
        return "invalid_input", _PUBLIC_MESSAGE["invalid_input"]
    if isinstance(exc, DataUnavailableError):
        return "data_unavailable", _PUBLIC_MESSAGE["data_unavailable"]
    if isinstance(exc, RateLimitError):
        return "rate_limited", _PUBLIC_MESSAGE["rate_limited"]
    if isinstance(exc, ServiceUnavailableError | DownloadError):
        return "upstream_unavailable", _PUBLIC_MESSAGE["upstream_unavailable"]
    if isinstance(exc, PydanticValidationError):
        return "invalid_input", _PUBLIC_MESSAGE["invalid_input"]
    return "internal_error", _PUBLIC_MESSAGE["internal_error"]


def _recovery_action(error_code: str) -> str:
    if error_code in _RETRYABLE:
        return "retry_backoff"
    # response_limit_exceeded: retrying the same request yields the same oversized
    # payload, so the recovery is to narrow the input (e.g. a smaller `limit`).
    if error_code in {"invalid_input", "not_found", "ambiguous_query", "response_limit_exceeded"}:
        return "reformulate_input"
    return "switch_tool"


def _error_envelope(exc: BaseException, context: McpErrorContext) -> dict[str, Any]:
    error_code, message = _classify(exc)
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        # Defensive backstop: no forbidden code points reach the caller whatever
        # the classify path (incl. McpToolError bodies authored in tools).
        "message": sanitize_message(message),
        "retryable": error_code in _RETRYABLE,
        "recovery_action": _recovery_action(error_code),
        "_meta": {
            "tool": context.tool_name,
            "request_id": _request_id(),
            **_UNSAFE_FOR_CLINICAL_USE_META,
        },
    }
    if isinstance(exc, InvalidInputError):
        # field/allowed_values/hint are server-authored; the whole-envelope pass
        # code-point-strips them (no interpolation of caller/upstream prose here).
        if exc.field is not None:
            envelope["field"] = exc.field
        if exc.allowed is not None:
            envelope["allowed_values"] = exc.allowed
        if exc.hint is not None:
            envelope["hint"] = exc.hint
    if isinstance(exc, WithdrawnEntryError):
        # Structured fields may come from the live fallback: validate identifiers,
        # drop non-conforming ones; the status is constrained to a simple token.
        replaced_by = _valid_records(exc.replaced_by)
        envelope["obsolete"] = True
        envelope["withdrawn_status"] = _valid_status(exc.withdrawn_status)
        envelope["replaced_by"] = replaced_by
        envelope["_meta"]["next_commands"] = withdrawn_recovery(replaced_by)
    elif isinstance(exc, AmbiguousQueryError) and (candidates := _valid_records(exc.candidates)):
        envelope["candidates"] = candidates
        # Every routed query is a validated MGI id, so the recovery command can
        # never carry attacker prose in its arguments.
        envelope["_meta"]["next_commands"] = [
            cmd("get_marker", query=c["mgi_id"]) for c in candidates[:3]
        ] or [cmd("get_server_capabilities")]
    elif context.fallback is not None:
        envelope["_meta"]["next_commands"] = [context.fallback]
    else:
        envelope["_meta"]["next_commands"] = default_error_next_commands(
            context.tool_name, error_code, context.arguments
        )
    # DEEPEST LESSON: a whole-envelope code-point backstop over every string leaf,
    # ON TOP OF the fixed-message + validated-identifier discipline above.
    return _sanitize_envelope(envelope)


def build_arg_error_envelope(
    *,
    tool_name: str,
    loc: str,
    error_type: str,
    valid_params: list[str],
    signature: str,
    suggestion: str | None,
    constraints: tuple[list[str], str] | None = None,
) -> dict[str, Any]:
    """Standard invalid-input envelope for an argument-binding failure.

    When ``constraints`` is supplied the failure is an invalid *value* on a known
    argument, so ``allowed_values`` carries the valid range/enum (not the list of
    argument *names*) and the message states the constraint.
    """
    # ``loc`` for a *missing* / invalid-*value* failure is a server-defined schema
    # parameter name (safe to echo). For an *unexpected* argument it is the
    # caller-invented NAME (arbitrary text) -- never echo that into the message
    # (a single-token instruction survives code-point stripping); it is only kept,
    # code-point-stripped, in the structured ``field`` value. safe_loc is stripped
    # for the ``field`` in every branch; the whole-envelope pass strips the rest.
    safe_loc = sanitize_message(loc)
    if constraints is not None:
        allowed, human = constraints
        message = f"Invalid value for argument `{safe_loc}` of {tool_name}: {human}."
        return _sanitize_envelope(
            {
                "success": False,
                "error_code": "invalid_input",
                "message": message,
                "retryable": False,
                "recovery_action": "reformulate_input",
                "field": safe_loc,
                "allowed_values": allowed,
                "hint": signature,
                "_meta": {
                    "tool": tool_name,
                    "request_id": _request_id(),
                    "next_commands": [cmd("get_server_capabilities")],
                    **_UNSAFE_FOR_CLINICAL_USE_META,
                },
            }
        )
    if error_type == "missing_argument":
        head = f"Missing required argument `{safe_loc}` for {tool_name}."
    elif error_type == "unexpected_keyword_argument":
        head = f"Unknown argument for {tool_name}."  # never echo the caller's name
    else:
        head = f"Invalid value for argument `{safe_loc}` of {tool_name}."
    dym = f" Did you mean `{suggestion}`?" if suggestion else ""
    message = f"{head}{dym} Valid argument names are listed in allowed_values."
    return _sanitize_envelope(
        {
            "success": False,
            "error_code": "invalid_input",
            "message": message,
            "retryable": False,
            "recovery_action": "reformulate_input",
            "field": safe_loc,
            "allowed_values": valid_params,
            "hint": signature,
            "_meta": {
                "tool": tool_name,
                "request_id": _request_id(),
                "next_commands": [cmd("get_server_capabilities")],
                **_UNSAFE_FOR_CLINICAL_USE_META,
            },
        }
    )


async def run_mcp_tool(
    tool_name: str,
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: McpErrorContext | None = None,
) -> dict[str, Any]:
    """Execute a tool body, returning the result dict or a structured error dict."""
    ctx = context or McpErrorContext(tool_name=tool_name)
    start = time.perf_counter()
    try:
        result = await call()
        if isinstance(result, dict):
            result.setdefault("success", True)
            existing_meta: dict[str, Any] = result.get("_meta") or {}
            result["_meta"] = {
                **existing_meta,
                "tool": tool_name,
                "request_id": _request_id(),
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
                # Merged in last (after existing_meta) so it always wins and can
                # never be stripped or overridden by a tool body's own _meta.
                **_UNSAFE_FOR_CLINICAL_USE_META,
            }
        return result
    except Exception as exc:  # broad catch is the error-boundary contract
        envelope = _error_envelope(exc, ctx)
        envelope["_meta"]["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "mcp_tool_error tool=%s code=%s exc=%s",
            tool_name,
            envelope["error_code"],
            exc.__class__.__name__,
        )
        return envelope
