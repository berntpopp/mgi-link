"""The README's ``## Tools`` table must match the registered tool surface exactly.

The README Standard v1 makes the table the advertised MCP surface, so it is
machine-verified rather than hand-maintained: adding or renaming a tool without
updating the table fails CI. The tool list is read from the live facade (the same
fixture ``test_tool_names.py`` uses), never hardcoded here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

README = Path(__file__).resolve().parents[2] / "README.md"

#: A table row whose first cell is a single backticked tool name.
_ROW_RE = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|")


def _readme_tools() -> set[str]:
    """Parse the tool names out of the README's ``## Tools`` table."""
    lines = README.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("## Tools")
    except ValueError:  # pragma: no cover - guarded by the assertion below
        return set()

    names: set[str] = set()
    for line in lines[start + 1 :]:
        if line.startswith("## "):  # next section: the table is behind us
            break
        match = _ROW_RE.match(line)
        if match:
            names.add(match.group(1))
    return names


async def test_readme_tools_table_matches_registered_tools(facade: Any) -> None:
    registered = {tool.name for tool in await facade.list_tools()}
    assert registered, "no tools registered on the facade"

    documented = _readme_tools()
    assert documented, "no tool rows found in the README '## Tools' table"

    assert documented == registered, (
        "README '## Tools' table has drifted from the registered tools.\n"
        f"  missing from README: {sorted(registered - documented)}\n"
        f"  not registered:      {sorted(documented - registered)}"
    )
