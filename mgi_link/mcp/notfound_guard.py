"""FastMCP-core not-found reflection guard (Response-Envelope v1.1 fast-follow).

FastMCP core (pinned ``>=3.4.4,<4.0.0``) reflects the caller's OWN requested tool
name / resource URI / prompt name back to the caller (and to logs) BEFORE any
backend middleware runs. This module closes that residual with fixed, input-free
messages built from CONSTANTS only, mirroring the ratified fleet references
(``mondo``/``hpo`` registry preflight, ``clinvar`` protocol backstop,
``panelapp``/``autopvs1``/``gnomad`` validation-log scrub filter).

The reflected text is *caller-supplied* (a caller self-reflection surface), so
this is materially lower-risk than the upstream-injection leak the prior sweep
closed. It is still worth closing: the reflected name/URI -- with any
control/zero-width/bidi/NUL code points -- lands in shared operator logs and in an
agent's tool-result context. Fixed constants remove the channel entirely.

Layers (spec 3), copied per repo (no shared runtime library exists fleet-wide):

* Layer 1 -- ``on_call_tool`` registry preflight: ``get_tool(name)`` returns
  ``None`` for an unknown/disabled tool, so we return a fixed, name-free
  ``not_found`` envelope BEFORE core dispatch. Closes the unknown-TOOL surface;
  never echoes ``_meta.tool``.
* Layer 2 -- ``on_read_resource`` boundary: a valid-but-unknown resource makes
  core raise ``NotFoundError("Unknown resource: '<uri>'")``; we re-raise a fixed
  URI-free ``ResourceError``. mgi-link's ``mgi://`` resources raise no
  author-authored ``ResourceError`` (they only return payloads), so every
  exception here is a core not-found/read failure and is replaced unconditionally
  -- ``str(exc)`` (which preserves injection prose) is never re-published.
* Layer 3 -- protocol-handler backstop: wraps the raw ``CallTool`` / ``ReadResource``
  / ``GetPrompt`` request handlers as the OUTERMOST layer. Replaces any non-envelope
  ``isError`` tool result (the unknown-tool *return* path) and re-raises fixed
  input-free messages for resource/prompt dispatch failures -- the ONLY layer that
  covers the unknown-PROMPT surface (FastMCP echoes ``Unknown prompt: '<name>'`` to
  the caller even when no prompts are registered).
* Layer 5 -- validation-log scrub filter: FastMCP's pre-middleware and the MCP SDK
  session's request-validation logs echo the raw name/URI (with code points) on
  their own loggers/handlers at DEBUG and WARNING. The filter neutralizes those
  records at the source logger so caller input never reaches a log sink.

Layer 4 (arg-validation) is the existing :class:`ArgValidationMiddleware`
(``middleware.py``). Layer 6 (OTel span redaction) is a no-op here: FastMCP pulls
in ``opentelemetry-api`` transitively but ``opentelemetry-sdk`` is absent, so the
tracer provider is non-recording -- no span exception attributes are ever captured,
so there is nothing to redact (fleet policy: do NOT add the SDK dependency).
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import mcp.types
from fastmcp.exceptions import NotFoundError as FastMCPNotFoundError
from fastmcp.exceptions import ResourceError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

from mgi_link.mcp.envelope import build_fixed_error_envelope

logger = logging.getLogger(__name__)

# Fixed, input-free public messages. They NEVER contain the requested name/URI
# (nor a ``_meta.tool`` echo of it): sanitation strips code points but not
# injection prose, so a fixed constant is the only safe source (prior-sweep
# lesson). ``not_found`` reuses this repo's error-code vocabulary (spec 3.1).
_UNKNOWN_TOOL_MESSAGE = "The requested tool is not available. Call get_server_capabilities."
_UNKNOWN_RESOURCE_MESSAGE = "The requested resource is not available."
_UNKNOWN_PROMPT_MESSAGE = "The requested prompt is not available."


def unknown_tool_envelope() -> dict[str, Any]:
    """Return a fixed, name-free ``not_found`` envelope dict for an unknown tool."""
    return build_fixed_error_envelope(
        error_code="not_found",
        message=_UNKNOWN_TOOL_MESSAGE,
        recovery_action="switch_tool",
    )


def _envelope_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope)


def unknown_tool_result() -> ToolResult:
    """Return the fixed unknown-tool envelope as a ``ToolResult``.

    Carries both ``structured_content`` and a matching TextContent JSON mirror,
    flagged ``is_error=True`` (the ratified fleet references' contract): an unknown
    tool has no registered output schema, so a non-isError structured result makes
    the caller's MCP client log the requested (caller-controlled) name in a "cannot
    validate structured content" warning -- ``is_error=True`` tells the client to
    skip that validation, closing that reflection path. The ``success=False`` /
    ``error_code`` envelope still lets callers branch as with every other error.
    """
    envelope = unknown_tool_envelope()
    return ToolResult(
        content=[TextContent(type="text", text=_envelope_json(envelope))],
        structured_content=envelope,
        is_error=True,
    )


class NotFoundGuard(Middleware):
    """Layer 1 (tool preflight) + Layer 2 (resource boundary)."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, ToolResult],
    ) -> ToolResult:
        """Preflight the tool NAME; an unknown name never reaches core dispatch.

        ``get_tool`` returns ``None`` (it does not raise) for an unknown or disabled
        tool, so an unknown name is answered here with a fixed, name-free envelope.
        Otherwise defer to the chain (arg-validation middleware + the tool body).
        """
        fctx = getattr(context, "fastmcp_context", None)
        name = getattr(getattr(context, "message", None), "name", None)
        if fctx is not None and isinstance(name, str):
            try:
                tool = await fctx.fastmcp.get_tool(name)
            except Exception:
                tool = object()  # resolution failure: defer to core, do not mask
            if tool is None:
                logger.warning("mcp_unknown_tool")
                return unknown_tool_result()
        return await call_next(context)

    async def on_read_resource(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        """Emit a FIXED, URI-free error for a resource not-found / read failure.

        The requested URI is caller-controlled; FastMCP core echoes it
        (``Unknown resource: '<uri>'`` / ``Error reading resource '<uri>'``) in both
        the direct exception and the protocol error. Re-raise a fixed message so the
        URI never reaches the caller/protocol. mgi-link raises no author-authored
        ``ResourceError``, so every exception here is replaced and ``str(exc)``
        (which preserves injection prose) is never re-published.
        """
        try:
            return await call_next(context)
        except FastMCPNotFoundError:
            logger.warning("mcp_resource_not_found")
            raise ResourceError(_UNKNOWN_RESOURCE_MESSAGE) from None
        except Exception as exc:
            logger.warning("mcp_resource_error error_type=%s", type(exc).__name__)
            raise ResourceError(_UNKNOWN_RESOURCE_MESSAGE) from None


# ---------------------------------------------------------------------------
# Layer 3 -- protocol-handler backstop (clinvar pattern)
# ---------------------------------------------------------------------------


class ProtocolError(Exception):
    """A dispatch-level failure re-raised with a FIXED, input-free message."""


def _is_structured_envelope(call_result: mcp.types.CallToolResult) -> bool:
    """True if an ``isError`` result carries one of OUR JSON envelopes.

    Distinguishes a structured mgi-link error (already name-free -- it has an
    ``error_code``; e.g. the Layer-1 unknown-tool frame) from a RAW FastMCP dispatch
    error whose plain-text message echoes the caller-supplied tool name
    (``Unknown tool: '<name>'``).
    """
    if not call_result.content:
        return False
    text = getattr(call_result.content[0], "text", None)
    if not isinstance(text, str):
        return False
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return False
    return isinstance(obj, dict) and "error_code" in obj


def _fixed_tool_not_found_server_result() -> mcp.types.ServerResult:
    """A fixed, name-free ServerResult for an unknown/failed tool dispatch."""
    envelope = unknown_tool_envelope()
    return mcp.types.ServerResult(
        mcp.types.CallToolResult(
            content=[mcp.types.TextContent(type="text", text=_envelope_json(envelope))],
            structuredContent=envelope,
            isError=True,
        )
    )


def install_protocol_error_handler(mcp_server: Any) -> None:
    """Wrap the tool/resource/prompt request handlers as the OUTERMOST layer.

    A FastMCP core not-found (or read) error can no longer reflect the
    caller-supplied name/URI. Install AFTER all tools/resources/prompts are
    registered so the handlers exist.
    """
    handlers = mcp_server._mcp_server.request_handlers

    call_tool = handlers.get(mcp.types.CallToolRequest)
    if call_tool is not None:

        async def wrapped_call_tool(
            request: mcp.types.CallToolRequest,
            *,
            _orig: Any = call_tool,
        ) -> mcp.types.ServerResult:
            try:
                result = cast(mcp.types.ServerResult, await _orig(request))
            except FastMCPNotFoundError:
                # Unknown-tool *raise* drift (should not reach here once Layer 1
                # is active) -- answer with the fixed name-free envelope.
                return _fixed_tool_not_found_server_result()
            # FastMCP *returns* an isError CallToolResult with a raw plain-text
            # message ("Unknown tool: '<name>'") for an unknown tool; replace any
            # isError result that is NOT one of our structured envelopes.
            root = getattr(result, "root", None)
            if (
                isinstance(root, mcp.types.CallToolResult)
                and root.isError
                and not _is_structured_envelope(root)
            ):
                return _fixed_tool_not_found_server_result()
            return result

        handlers[mcp.types.CallToolRequest] = wrapped_call_tool

    for request_type, message in (
        (mcp.types.ReadResourceRequest, _UNKNOWN_RESOURCE_MESSAGE),
        (mcp.types.GetPromptRequest, _UNKNOWN_PROMPT_MESSAGE),
    ):
        orig = handlers.get(request_type)
        if orig is None:
            continue

        async def wrapped(
            request: Any,
            *,
            _orig: Any = orig,
            _message: str = message,
        ) -> Any:
            try:
                return await _orig(request)
            except Exception:
                # Re-raise with a FIXED, input-free message so no requested
                # name/URI (or its code points) reaches the JSON-RPC error frame.
                raise ProtocolError(_message) from None

        handlers[request_type] = wrapped


# ---------------------------------------------------------------------------
# Layer 5 -- validation-log scrub filter (panelapp/autopvs1/gnomad pattern)
# ---------------------------------------------------------------------------
#
# Each marker is a substring of the ``record.msg`` (f-string prefix or %-template)
# of a FastMCP-core / MCP-SDK record that reflects the caller-supplied name/URI
# (carried in ``args`` or interpolated into the message). Matching on ``msg``
# covers both forms because the scrub replaces the message AND clears args.
_SCRUB_MARKERS: tuple[str, ...] = (
    "Handler called: call_tool",
    "Handler called: read_resource",
    "Handler called: get_prompt",
    "Tool cache miss for",
    "Invalid arguments for tool",
    "Error calling tool",
    "Error reading resource",
    "Failed to validate request",
    "Failed to validate notification",
    "Message that failed validation",
)

# The source loggers on which those records are CREATED. A logging filter runs
# only for records emitted on the logger it is attached to (ancestor filters are
# skipped during propagation, but HANDLER-level filters DO run during
# propagation), so attach directly to each originating logger -- including the
# ROOT logger, where ``mcp.shared.session`` emits its request-validation failures
# via a bare ``logging.warning``, and FastMCP's own non-propagating ``fastmcp``
# logger, whose Rich handlers would otherwise bypass a root-only filter.
_SCRUB_LOGGERS: tuple[str, ...] = (
    "",  # root -- mcp.shared.session request-validation failures
    "mcp.shared.session",
    "fastmcp",  # non-propagating parent + its Rich handlers (handler-level scrub)
    "fastmcp.server.server",
    "fastmcp.server.mixins.mcp_operations",
    "mcp",
    "mcp.server.lowlevel.server",
)

_SCRUBBED_MESSAGE = "MCP request rejected (details omitted)."


class _NotFoundLogScrubFilter(logging.Filter):
    """Scrub log records that would echo a caller-supplied tool name / URI.

    Replaces the record payload with a fixed message (clearing ``args`` /
    ``exc_info`` / ``exc_text`` / ``stack_info``) so the caller-chosen name/URI --
    and any control/zero-width/bidi/NUL code points it carries -- can never reach a
    log or telemetry sink. Always returns ``True``: the (now input-free) record is
    still emitted for operational visibility.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg if isinstance(record.msg, str) else ""
        if any(marker in msg for marker in _SCRUB_MARKERS):
            record.msg = _SCRUBBED_MESSAGE
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


#: One shared filter instance so idempotent installs never stack duplicates.
_SHARED_FILTER = _NotFoundLogScrubFilter()


def _has_filter(target: logging.Logger | logging.Handler) -> bool:
    return any(isinstance(existing, _NotFoundLogScrubFilter) for existing in target.filters)


def install_notfound_log_filter() -> None:
    """Idempotently attach the scrub filter to each source logger (and its handlers).

    Call after the FastMCP facade is built, so the framework Rich handlers already
    exist. Process-global; safe to call more than once.
    """
    for name in _SCRUB_LOGGERS:
        target = logging.getLogger(name)
        if not _has_filter(target):
            target.addFilter(_SHARED_FILTER)
        for handler in target.handlers:
            if not _has_filter(handler):
                handler.addFilter(_SHARED_FILTER)
