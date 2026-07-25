"""Configuration validation.

The tests that matter here are the refusals. Wasl's crawl ethics are only real if
they are enforced in code, and the cheapest way to prove that is a test asserting
the process declines to proceed when its identity is unconfigured.
"""

from __future__ import annotations

import pytest

from wasl.config import ConfigurationError, Settings

BASE = {
    "database_url": "postgresql://u:p@localhost:5432/wasl",
    "redis_url": "redis://localhost:6379/0",
}


def test_accepts_a_valid_configuration() -> None:
    settings = Settings(**BASE)
    assert settings.env == "development"
    assert settings.playwright_available is True


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("database_url", "", "required"),
        ("database_url", "mysql://u:p@localhost/wasl", "must be a postgresql URL"),
        ("redis_url", "", "required"),
        ("redis_url", "http://localhost:6379", "must start with redis://"),
        ("crawler_info_url", "ftp://example.com/crawler", "must be an https URL"),
    ],
)
def test_rejects_invalid_values(field: str, value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings(**{**BASE, field: value})


def test_http_localhost_is_allowed_for_the_info_url() -> None:
    """Local development must not require a TLS certificate."""
    settings = Settings(**BASE, crawler_info_url="http://localhost:3000/crawler")
    assert settings.crawler_info_url.endswith("/crawler")


def test_refuses_to_crawl_without_a_configured_identity() -> None:
    """A User-Agent advertising a URL nobody can read is dishonest identification."""
    settings = Settings(**BASE)
    with pytest.raises(ConfigurationError) as exc:
        settings.require_crawler_identity()
    assert "WASL_CRAWLER_INFO_URL" in str(exc.value)
    assert "WASL_OPT_OUT_EMAIL" in str(exc.value)


def test_refuses_to_crawl_with_only_half_an_identity() -> None:
    settings = Settings(**BASE, crawler_info_url="https://example.com/crawler")
    with pytest.raises(ConfigurationError, match="WASL_OPT_OUT_EMAIL"):
        settings.require_crawler_identity()


def test_user_agent_is_built_from_the_validated_identity() -> None:
    settings = Settings(
        **BASE,
        crawler_info_url="https://example.com/crawler",
        opt_out_email="crawler@example.com",
    )
    ua = settings.user_agent()
    assert ua.startswith("WaslAI-Research/")
    assert "(+https://example.com/crawler)" in ua


def test_user_agent_refuses_when_identity_is_missing() -> None:
    """The refusal must hold at the point the string is built, not just at config time."""
    with pytest.raises(ConfigurationError):
        Settings(**BASE).user_agent()


def test_derived_paths_hang_off_the_data_dir() -> None:
    from pathlib import Path

    settings = Settings(**BASE, data_dir=Path("/srv/wasl"))
    assert settings.cache_dir == Path("/srv/wasl/cache")
    assert settings.artifacts_dir == Path("/srv/wasl/artifacts")
    assert settings.reference_dir == Path("/srv/wasl/reference")


def test_settings_are_immutable() -> None:
    """Configuration must not drift mid-process."""
    settings = Settings(**BASE)
    with pytest.raises(ValueError):
        settings.env = "production"  # type: ignore[misc]


def test_opt_out_contact_accepts_an_https_url() -> None:
    """A monitored issue tracker is a real opt-out channel.

    The requirement is somewhere a site operator can reach that a human reads,
    not specifically SMTP — and the published crawler page offers exactly this,
    so the config must not disagree with it.
    """
    settings = Settings(
        **BASE,
        crawler_info_url="https://example.com/crawler",
        opt_out_email="https://github.com/owner/repo/issues",
    )
    assert settings.require_crawler_identity()[1].startswith("https://")


def test_opt_out_contact_rejects_a_value_that_is_neither() -> None:
    with pytest.raises(ValueError, match="email address or an https URL"):
        Settings(**BASE, opt_out_email="ask me on linkedin")
