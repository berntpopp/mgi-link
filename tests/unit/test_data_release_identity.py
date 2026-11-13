"""The released app, its config default, and the release gate bind ONE data release."""

import json
from pathlib import Path

from mgi_link.config import ImmutableDataRequirement

ROOT = Path(__file__).resolve().parents[2]


def test_container_release_binds_the_config_default_data_release() -> None:
    config = json.loads((ROOT / "container-release.json").read_text(encoding="utf-8"))
    requirement = ImmutableDataRequirement()

    assert config["data"]["mode"] == "external-reference"
    assert config["data"]["release_tag"] == requirement.release_tag
    assert config["data"]["digest"] == f"sha256:{requirement.compressed_sha256}"
    assert config["data"]["schema_compatibility"] == ["1"]
    assert config["data_identity_contract"] == "runtime-v1"
    assert config["smoke"] == {"profile": "immutable-bundle"}
    assert [aux["name"] for aux in config["service"]["auxiliary"]] == ["mgi-data-init"]


def test_no_compose_file_refreshes_from_upstream_at_boot() -> None:
    for path in (ROOT / "docker").glob("docker-compose*.yml"):
        text = path.read_text(encoding="utf-8")
        assert 'REFRESH_ENABLED: "true"' not in text, path
        assert "REFRESH_ENABLED=true" not in text, path
        assert "mgi-link-data refresh" not in text, path
        assert "materialize-data" in text or "!reset" in text, path
