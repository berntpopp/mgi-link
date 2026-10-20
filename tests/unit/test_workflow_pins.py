"""Release workflow pins must track the trusted fleet revisions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTER_SHA = "e8931f0114bba3568517d1c7b1f990bea2be31af"
SETUP_UV_SHA = "1c37ad07a6a961277cf70c0d37d6f313000f5884"
CODEQL_SHA = "6f2ac81f5cd81fe351a197ba0b00d91d03cd2aee"


def test_release_workflows_pin_the_trusted_router_and_actions() -> None:
    workflows = ROOT / ".github" / "workflows"
    assert ROUTER_SHA in (workflows / "container-release.yml").read_text(encoding="utf-8")
    assert ROUTER_SHA in (workflows / "container-ci.yml").read_text(encoding="utf-8")
    assert SETUP_UV_SHA in (workflows / "ci.yml").read_text(encoding="utf-8")
    assert (workflows / "security.yml").read_text(encoding="utf-8").count(CODEQL_SHA) == 2
