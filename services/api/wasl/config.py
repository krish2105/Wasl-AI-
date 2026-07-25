"""Runtime configuration, read once from the process environment.

Why this exists rather than `pydantic-settings`: that is a separate package and
is not on the locked dependency list, and the amount of behaviour we need from
it is one `os.environ` read per field. A plain Pydantic model gives us the
validation and the type safety without the dependency.

Two design decisions worth knowing:

1. **Crawler identity is validated lazily, not at import.** The API must be able
   to boot, serve `/health` and run its test suite without a configured crawler
   identity. But `require_crawler_identity()` raises before any network call is
   made, so a crawl cannot start while the User-Agent points at nothing. See
   `ethics` below.

2. **The rate limit and page caps are not here.** They live as module constants
   in `wasl.crawler.policy` precisely so that no environment variable, config
   file or API caller can raise them.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Environment = Literal["development", "test", "production"]


class ConfigurationError(RuntimeError):
    """Raised when the process is configured in a way that is unsafe to run."""


def _repo_root() -> Path:
    """Repository root, found by walking up for a marker."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "seeds" / "seed_urls.yaml").exists() or (candidate / ".git").is_dir():
            return candidate
    return here.parents[3]


def _resolve_data_dir(raw: str) -> Path:
    """Anchor a relative WASL_DATA_DIR to the repo root, not the working directory.

    `./data` resolved against cwd meant the crawl cache landed in a different
    place depending on where a command was run from — so the cache silently
    failed at its only job, which is to stop us re-fetching third-party sites.
    It also put cached pages outside the path .gitignore was anchored to.

    An absolute path is honoured as given; containers set /data.
    """
    path = Path(raw)
    return path if path.is_absolute() else (_repo_root() / path).resolve()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated list, e.g. WASL_CORS_ORIGINS=https://a.app,https://b.app"""
    raw = _env(name)
    if not raw:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


class Settings(BaseModel):
    """Everything the application reads from the environment."""

    model_config = {"frozen": True, "extra": "forbid"}

    env: Environment = "development"
    log_level: str = "INFO"

    database_url: str
    redis_url: str

    # Browser origins allowed to call this API. Localhost is included so a
    # developer needs no configuration; a deployed frontend must be named
    # explicitly, because `allow_origins=["*"]` on an API that spends real crawl
    # budget lets anyone else's page spend it.
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    data_dir: Path = Field(default=Path("./data"))

    # --- crawler identity ----------------------------------------------------
    # Empty is allowed at construction so the API can boot. It is NOT allowed at
    # crawl time — see require_crawler_identity().
    crawler_info_url: str = ""
    opt_out_email: str = ""
    playwright_available: bool = True

    # --- model providers (all free tier; a paid key here is a bug) -----------
    groq_api_key: str = ""
    google_api_key: str = ""
    cerebras_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # --- observability -------------------------------------------------------
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3001"
    otel_endpoint: str = ""
    otel_service_name: str = "wasl-api"

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL is required")
        if not v.startswith("postgresql"):
            raise ValueError(f"DATABASE_URL must be a postgresql URL, got {v.split(':', 1)[0]!r}")
        return v

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, v: str) -> str:
        if not v:
            raise ValueError("REDIS_URL is required")
        if not v.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must start with redis:// or rediss://")
        return v

    @field_validator("crawler_info_url")
    @classmethod
    def _validate_info_url(cls, v: str) -> str:
        if v and not v.startswith("https://") and not v.startswith("http://localhost"):
            raise ValueError(
                "WASL_CRAWLER_INFO_URL must be an https URL (http is allowed only for localhost)"
            )
        return v

    @field_validator("opt_out_email")
    @classmethod
    def _validate_opt_out_contact(cls, v: str) -> str:
        """Accepts an email address OR an https URL.

        The requirement is a channel a site operator can reach and that someone
        actually reads — not specifically SMTP. A public issue tracker satisfies
        that, and demanding an email while the published crawler page offers a
        GitHub issue would make the two disagree about how to opt out.
        """
        if not v:
            return v
        if v.startswith("https://"):
            return v
        if "@" in v and "." in v.split("@")[-1]:
            return v
        raise ValueError(
            "WASL_OPT_OUT_EMAIL must be an email address or an https URL to a "
            f"monitored channel (an issue tracker counts). Got {v!r}."
        )

    # --- derived paths -------------------------------------------------------

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def reference_dir(self) -> Path:
        return self.data_dir / "reference"

    # --- ethics --------------------------------------------------------------

    def require_crawler_identity(self) -> tuple[str, str]:
        """Return (info_url, opt_out_email), or refuse to let a crawl proceed.

        A User-Agent that advertises a URL nobody can read is dishonest
        identification, and honest identification is the one thing the crawl
        ethics rules treat as non-negotiable. So this is a hard failure, not a
        warning: if the info page is not live and configured, Wasl does not
        fetch anything.

        Raises:
            ConfigurationError: if either value is missing.
        """
        missing = [
            name
            for name, value in (
                ("WASL_CRAWLER_INFO_URL", self.crawler_info_url),
                ("WASL_OPT_OUT_EMAIL", self.opt_out_email),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                f"Refusing to crawl: {' and '.join(missing)} not set. The crawler's "
                "User-Agent must point at a live page explaining what it does, and an "
                "opt-out channel someone reads — an email address or an https URL to a "
                "monitored issue tracker. Set both in .env."
            )
        return self.crawler_info_url, self.opt_out_email

    def user_agent(self) -> str:
        """The User-Agent string, built from the validated identity."""
        info_url, _ = self.require_crawler_identity()
        return f"WaslAI-Research/{_version()} (+{info_url})"


def _version() -> str:
    from wasl import __version__

    return __version__


def load_settings() -> Settings:
    """Build Settings from the current process environment."""
    return Settings(
        env=_env("WASL_ENV", "development"),  # type: ignore[arg-type]
        log_level=_env("WASL_LOG_LEVEL", "INFO"),
        database_url=_env("DATABASE_URL"),
        redis_url=_env("REDIS_URL"),
        cors_origins=_env_list("WASL_CORS_ORIGINS", ("http://localhost:3000",)),
        data_dir=_resolve_data_dir(_env("WASL_DATA_DIR", "./data")),
        crawler_info_url=_env("WASL_CRAWLER_INFO_URL"),
        opt_out_email=_env("WASL_OPT_OUT_EMAIL"),
        playwright_available=_env_bool("WASL_PLAYWRIGHT_AVAILABLE", True),
        groq_api_key=_env("GROQ_API_KEY"),
        google_api_key=_env("GOOGLE_API_KEY"),
        cerebras_api_key=_env("CEREBRAS_API_KEY"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434"),
        langfuse_public_key=_env("LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=_env("LANGFUSE_SECRET_KEY"),
        langfuse_host=_env("LANGFUSE_HOST", "http://localhost:3001"),
        otel_endpoint=_env("OTEL_EXPORTER_OTLP_ENDPOINT"),
        otel_service_name=_env("OTEL_SERVICE_NAME", "wasl-api"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Call `get_settings.cache_clear()` in tests."""
    return load_settings()
