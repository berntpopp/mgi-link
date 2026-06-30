"""Tool-name compliance with the GeneFoundry Tool-Naming Standard v1.

Every registered tool must be unprefixed, snake_case, <= 50 chars, and start with
a canonical verb so it composes cleanly behind the ``genefoundry-router`` gateway,
which mounts this server under the ``mgi`` namespace (tools surface as
``mgi_<tool>``). Guards against future drift. See issue berntpopp/mgi-link#1.
"""

from __future__ import annotations

import re
from typing import Any

_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
# Tier-1 read/query canon — Tool-Naming Standard v1.1, ratified 2026-06-30.
_CANONICAL_VERBS = frozenset(
    {"get", "search", "list", "resolve", "find", "compare", "compute", "map"}
)
# Tier-2 sanctioned action/compute verbs — v1.1.
_TIER2_VERBS = frozenset(
    {
        "predict",
        "annotate",
        "recode",
        "liftover",
        "analyze",
        "score",
        "submit",
        "export",
        "generate",
        "download",
    }
)
_ALLOWED_VERBS = _CANONICAL_VERBS | _TIER2_VERBS
_NAMESPACE = "mgi"


async def test_tool_names_conform_to_standard_v1(facade: Any) -> None:
    tools = await facade.list_tools()
    assert tools, "no tools registered on the facade"
    for tool in tools:
        name = tool.name
        tags = set(tool.tags or ())
        assert _NAME_RE.match(name), f"{name!r} must match ^[a-z0-9_]{{1,50}}$"
        assert not name.startswith(f"{_NAMESPACE}_"), (
            f"{name!r} must not self-prefix the '{_NAMESPACE}' namespace "
            "token — the gateway adds it"
        )
        # ops/meta tools (health checks, warmup, diagnostics, etc.) are exempt
        # from the verb rule — fleet ops/meta carve-out (v1.1).
        if "ops" in tags or "meta" in tags:
            continue
        assert name.split("_", 1)[0] in _ALLOWED_VERBS, (
            f"{name!r} must start with a canonical verb {sorted(_ALLOWED_VERBS)}"
        )
