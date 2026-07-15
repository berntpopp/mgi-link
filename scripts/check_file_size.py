#!/usr/bin/env python3
"""Enforce a per-file line budget to keep modules focused and reviewable.

Run via `make lint-loc`. Fails (exit 1) if any tracked Python file exceeds the
soft cap, so a module that has grown too large gets split rather than sprawling.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_LINES = 500
ROOTS = ("mgi_link", "tests")
EXTRA_FILES = ("server.py", "mcp_server.py")
# Vendored, byte-identical fleet conformance gates: they are copied verbatim from
# the router repo and MUST NOT be split, so they are exempt from the line budget.
EXEMPT_DIRS = ("tests/conformance",)


def main() -> int:
    """Report files over the line budget; return non-zero if any are found."""
    repo = Path(__file__).resolve().parents[1]
    offenders: list[tuple[Path, int]] = []
    paths: list[Path] = [repo / f for f in EXTRA_FILES]
    for root in ROOTS:
        paths.extend((repo / root).rglob("*.py"))
    for path in paths:
        if not path.exists():
            continue
        rel_posix = path.relative_to(repo).as_posix()
        if any(rel_posix.startswith(f"{d}/") for d in EXEMPT_DIRS):
            continue
        lines = path.read_text(encoding="utf-8").count("\n") + 1
        if lines > MAX_LINES:
            offenders.append((path.relative_to(repo), lines))
    for rel, lines in sorted(offenders):
        print(f"{rel}: {lines} lines (> {MAX_LINES})")
    if offenders:
        print(f"\n{len(offenders)} file(s) exceed the {MAX_LINES}-line budget.")
        return 1
    print(f"OK: all files within the {MAX_LINES}-line budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
