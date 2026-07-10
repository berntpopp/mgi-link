"""Configuration management for mgi-link.

Settings load from environment variables with the ``MGI_LINK_`` prefix (nested
models use ``__``, e.g. ``MGI_LINK_DATA__DB_FILENAME=mgi.sqlite`` or
``MGI_LINK_MOUSEMINE__ENABLE_LIVE_FALLBACK=true``) and an optional ``.env`` file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mgi_link import __version__

# Project root: <repo>/mgi_link/config.py -> <repo>
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

#: MGI publishes tab-delimited bulk reports under this directory.
DEFAULT_REPORTS_BASE_URL = "https://www.informatics.jax.org/downloads/reports"

#: The reports the index is built from: logical key -> report filename. The key
#: is the stable handle used in the download cache and the build pipeline.
REPORT_FILENAMES: dict[str, str] = {
    "markers": "MRK_List2.rpt",
    "alleles": "MGI_PhenotypicAllele.rpt",
    "genepheno": "MGI_GenePheno.rpt",
    "mp_vocab": "VOC_MammalianPhenotype.rpt",
    "mp_obo": "MPheno_OBO.ontology",
    "ortholog": "HOM_MouseHumanSequence.rpt",
    "disease": "MGI_DO.rpt",
    "ensembl": "MRK_ENSEMBL.rpt",
}

#: The report whose freshness drives a conditional rebuild (the phenotype
#: annotations change most often and are the core of this server).
PRIMARY_REPORT_KEY = "genepheno"

DEFAULT_MOUSEMINE_URL = "https://www.mousemine.org/mousemine/service"

#: Non-personal project contact advertised in outbound User-Agent headers when
#: no operator mailbox is configured. Never default to a personal email.
PROJECT_CONTACT_URL = "https://github.com/berntpopp/mgi-link"


class MgiDataConfig(BaseModel):
    """Local data store: bulk MGI reports -> built SQLite index."""

    data_dir: Path = Field(
        default=_DEFAULT_DATA_DIR,
        description="Directory holding the built SQLite database and download cache.",
    )
    db_filename: str = Field(
        default="mgi.sqlite",
        description="SQLite database filename within data_dir.",
    )
    reports_base_url: str = Field(
        default=DEFAULT_REPORTS_BASE_URL,
        description="Base URL of the MGI bulk data reports directory.",
    )
    download_timeout: int = Field(
        default=300,
        ge=5,
        le=1800,
        description="HTTP timeout (seconds) for downloading an MGI bulk report.",
    )
    max_download_bytes: int = Field(
        default=1 << 30,
        gt=0,
        description=(
            "Maximum report size; the largest report measured below 512 MiB on "
            "2026-07-10. Override for verified larger upstream artifacts."
        ),
    )
    max_download_seconds: float = Field(
        default=1800.0,
        gt=0,
        description=(
            "Maximum elapsed seconds while streaming one report; downloads measured "
            "below 900 seconds on 2026-07-10."
        ),
    )
    user_agent: str = Field(
        default=f"mgi-link/{__version__} (+{PROJECT_CONTACT_URL})",
        description="User-Agent sent to informatics.jax.org.",
    )
    auto_bootstrap: bool = Field(
        default=True,
        description="Build the database on first use by downloading the reports if absent.",
    )
    refresh_enabled: bool = Field(
        default=False,
        description=(
            "Run an in-process scheduler (unified/http transports only) that "
            "conditionally refreshes the database on an interval. Default OFF: MGI "
            "reports are best refreshed by an external cron job (see docs/deployment.md)."
        ),
    )
    refresh_interval_hours: float = Field(
        default=168.0,
        ge=1.0,
        le=720.0,
        description=(
            "Hours between conditional refresh checks (when refresh_enabled). MGI "
            "reports update roughly weekly; a weekly check is cheap because unchanged "
            "reports 304."
        ),
    )
    refresh_jitter_seconds: int = Field(
        default=600,
        ge=0,
        le=86400,
        description="Random jitter added to each refresh to avoid thundering herds.",
    )
    build_lock_timeout: int = Field(
        default=900,
        ge=1,
        le=7200,
        description="Seconds to wait for the cross-process build lock before giving up.",
    )
    cache_size: int = Field(
        default=1024,
        ge=0,
        le=65536,
        description="Max entries in the in-process query cache (0 disables).",
    )
    cache_ttl: int = Field(
        default=3600,
        ge=0,
        le=86400,
        description="Query cache TTL in seconds.",
    )

    @property
    def db_path(self) -> Path:
        """Absolute path to the SQLite database file."""
        return self.data_dir / self.db_filename

    def report_url(self, key: str) -> str:
        """Full URL of a report by its logical key."""
        return f"{self.reports_base_url.rstrip('/')}/{REPORT_FILENAMES[key]}"

    @field_validator("data_dir")
    @classmethod
    def _expand_data_dir(cls, v: Path) -> Path:
        return Path(v).expanduser()

    @field_validator("reports_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


class MouseMineConfig(BaseModel):
    """Optional live MouseMine (InterMine) enrichment / fallback."""

    base_url: str = Field(
        default=DEFAULT_MOUSEMINE_URL,
        description="MouseMine InterMine web-service base URL.",
    )
    contact_email: str = Field(
        default="",
        description=(
            "Optional operator contact email embedded in the MouseMine User-Agent. "
            "Empty by default (a non-personal project URL is advertised instead); "
            "set a monitored mailbox to give MGI/MouseMine a way to reach you."
        ),
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=120,
        description="Per-request timeout (seconds) for MouseMine.",
    )
    rate_limit_per_s: float = Field(
        default=2.0,
        ge=0.1,
        le=10.0,
        description="Max MouseMine requests per second (MGI servers are slow).",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=6,
        description="Retry attempts for transient (429/5xx/network) MouseMine failures.",
    )
    enable_live_fallback: bool = Field(
        default=False,
        description=(
            "Allow enrichment tools to query MouseMine live (off by default — the "
            "offline index serves the core surface deterministically)."
        ),
    )

    @property
    def user_agent(self) -> str:
        """User-Agent string; a project URL unless an operator mailbox is set."""
        contact = (
            f"mailto:{self.contact_email}" if self.contact_email else f"+{PROJECT_CONTACT_URL}"
        )
        return f"mgi-link/{__version__} ({contact})"

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        """Normalise the endpoint URL (no trailing slash)."""
        return v.rstrip("/")


class ServerSettings(BaseSettings):
    """Top-level server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="MGI_LINK_",
        env_nested_delimiter="__",
    )

    host: str = Field(default="127.0.0.1", description="Server host.")
    port: int = Field(default=8000, ge=1024, le=65535, description="Server port.")
    reload: bool = Field(default=False, description="Enable auto-reload in development.")

    transport: Literal["unified", "http", "stdio"] = Field(
        default="unified",
        description="Server transport mode.",
    )
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path.")
    allowed_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1", "::1"],
        description="Exact Host header values accepted by the request guard.",
    )
    allowed_origins: list[str] = Field(
        default=[],
        description="Browser Origin values accepted by the request guard.",
    )

    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins.",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level.",
    )
    log_format: Literal["json", "console"] = Field(
        default="console",
        description="Log format.",
    )

    data: MgiDataConfig = Field(
        default_factory=MgiDataConfig,
        description="Local data store configuration.",
    )
    mousemine: MouseMineConfig = Field(
        default_factory=MouseMineConfig,
        description="Live MouseMine enrichment configuration.",
    )

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure the MCP path starts with a forward slash."""
        return v if v.startswith("/") else f"/{v}"

    @field_validator("allowed_hosts", "allowed_origins", "cors_origins", mode="before")
    @classmethod
    def parse_string_list(cls, v: Any) -> list[str]:
        """Parse string lists from a comma-separated value or list."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return list(v) if v else []

    @field_validator("allowed_hosts")
    @classmethod
    def reject_wildcard_host(cls, v: list[str]) -> list[str]:
        """Require exact hosts; pattern syntax makes the boundary ambiguous."""
        if any(any(marker in host for marker in "*?[]") for host in v):
            raise ValueError("wildcard patterns are not allowed in allowed_hosts")
        return v


settings = ServerSettings()


def get_data_config() -> MgiDataConfig:
    """Return the active data-store configuration (used by the ingest CLI)."""
    return settings.data
