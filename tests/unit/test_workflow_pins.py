"""Release workflow pins must track the trusted fleet revisions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTER_SHA = "adfc1cffed6530d6453c9dbb40be5f4c5884b8a2"
SETUP_UV_SHA = "c18668ad3cf93ea998bef934396af7bb5c839dc7"
CODEQL_SHA = "2892aa5e19bbd11bc0cff5427e3b750a04d9e3c2"


def test_release_workflows_pin_the_trusted_router_and_actions() -> None:
    workflows = ROOT / ".github" / "workflows"
    assert ROUTER_SHA in (workflows / "container-release.yml").read_text(encoding="utf-8")
    assert ROUTER_SHA in (workflows / "container-ci.yml").read_text(encoding="utf-8")
    assert SETUP_UV_SHA in (workflows / "ci.yml").read_text(encoding="utf-8")
    assert (workflows / "security.yml").read_text(encoding="utf-8").count(CODEQL_SHA) == 2
