"""Deploy contract guard: the fleet controller's runtime observer proves the
effective uid from /proc, so the deployed NPM overlay must declare a numeric
non-root `user` for every service; the release Compose files feed the shared
release gate instead, which forbids `user` there entirely."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
NUMERIC_USER = re.compile(r"^[1-9][0-9]*:[1-9][0-9]*$")


class _TagTolerantLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Compose's custom `!reset` / `!override` tags."""


_TagTolerantLoader.add_multi_constructor(
    "!",
    lambda loader, _suffix, node: (
        loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None
    ),
)


def _load_compose(path: Path) -> dict:
    # _TagTolerantLoader subclasses yaml.SafeLoader (no arbitrary object construction);
    # ruff cannot see that through the subclass indirection.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_TagTolerantLoader)  # noqa: S506


def test_npm_overlay_declares_numeric_user_for_every_service() -> None:
    compose = _load_compose(ROOT / "docker" / "docker-compose.npm.yml")
    services = compose["services"]
    assert services, "docker-compose.npm.yml should declare at least one service"
    for name, svc in services.items():
        user = svc.get("user")
        assert user and NUMERIC_USER.match(str(user)), (
            f"service {name!r} in docker-compose.npm.yml must declare a numeric "
            f"'user: \"uid:gid\"' (got {user!r}) so the fleet controller's "
            "deployment_preflight can accept and verify the deployed overlay."
        )


def test_release_compose_files_never_declare_user() -> None:
    release_config = json.loads((ROOT / "container-release.json").read_text(encoding="utf-8"))
    for compose_path in release_config["service"]["compose_files"]:
        compose = _load_compose(ROOT / compose_path)
        for name, svc in compose.get("services", {}).items():
            assert "user" not in svc, (
                f"service {name!r} in {compose_path} must not declare 'user'; "
                "the shared release gate (container_release.py validate-compose, "
                "ALLOWED_SERVICE_KEYS) forbids it there."
            )
