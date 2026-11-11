"""Release workflow pins must track the trusted fleet revisions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTER_SHA = "5fed6be02ea0a598b56f7d1a69efcc47ff5796c8"
SETUP_UV_SHA = "68559e99cc807c1eb7e9238fd43a15bba460eec2"
CODEQL_SHA = "9b3254085494b55a0f7c4c2b3d2d52cc712ce370"


def test_release_workflows_pin_the_trusted_router_and_actions() -> None:
    workflows = ROOT / ".github" / "workflows"
    assert ROUTER_SHA in (workflows / "container-release.yml").read_text(encoding="utf-8")
    assert ROUTER_SHA in (workflows / "container-ci.yml").read_text(encoding="utf-8")
    assert SETUP_UV_SHA in (workflows / "ci.yml").read_text(encoding="utf-8")
    assert (workflows / "security.yml").read_text(encoding="utf-8").count(CODEQL_SHA) == 2
