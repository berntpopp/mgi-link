"""``docs/configuration.md`` must document every ``MGI_LINK_*`` variable, exactly.

README Standard v1 makes the configuration page the advertised settings surface:
the README says it covers *every* ``MGI_LINK_*`` variable, and deployment.md calls
it "the full reference". A documented fact that no machine checks will rot — and a
silently undocumented setting is worse than a long page (``MGI_LINK_CORS_ORIGINS``
is a live, browser-facing allowlist that once went unmentioned).

The env-var names are derived from the live settings model, never hardcoded here.
Adding a field to ``mgi_link/config.py`` without documenting it fails CI; so does
documenting a variable the model does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from mgi_link.config import ServerSettings

_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DOC = _ROOT / "docs" / "configuration.md"
ENV_EXAMPLE = _ROOT / ".env.example"

#: A ``MGI_LINK_*`` name in backticks (docs) — the prefix alone must not match.
_DOC_VAR_RE = re.compile(r"`(MGI_LINK_[A-Z0-9_]+)`")

#: A (commented-out) assignment in ``.env.example``.
_ENV_VAR_RE = re.compile(r"^#?\s*(MGI_LINK_[A-Z0-9_]+)=", re.MULTILINE)


def _env_names(model: type[BaseModel], prefix: str) -> set[str]:
    """Every environment-variable name the settings model reads, recursively."""
    names: set[str] = set()
    for field, info in model.model_fields.items():
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names |= _env_names(annotation, f"{prefix}{field.upper()}__")
        else:
            names.add(f"{prefix}{field.upper()}")
    return names


def test_configuration_doc_documents_every_setting() -> None:
    live = _env_names(ServerSettings, "MGI_LINK_")
    assert len(live) > 20, "settings model looks empty; the check would be vacuous"

    documented = set(_DOC_VAR_RE.findall(CONFIG_DOC.read_text(encoding="utf-8")))

    assert documented == live, (
        "docs/configuration.md has drifted from mgi_link/config.py.\n"
        f"  undocumented settings: {sorted(live - documented)}\n"
        f"  documented but not a real setting: {sorted(documented - live)}"
    )


def test_env_example_names_are_real_settings() -> None:
    """``.env.example`` is a scoped starting point, but it must not invent keys."""
    live = _env_names(ServerSettings, "MGI_LINK_")
    sampled = set(_ENV_VAR_RE.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))

    assert sampled, "no MGI_LINK_* keys found in .env.example"
    assert sampled <= live, f"unknown keys in .env.example: {sorted(sampled - live)}"


def test_env_example_carries_the_cors_allowlist() -> None:
    """CORS_ORIGINS is live, non-empty by default, and browser-facing: show it."""
    sampled = set(_ENV_VAR_RE.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))
    assert "MGI_LINK_CORS_ORIGINS" in sampled
