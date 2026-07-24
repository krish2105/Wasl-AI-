"""Crawl policy.

The tests that earn their keep here are the refusals and the ordering. A policy
that allows the right things is table stakes; one that refuses the right things,
in the right order, is the whole point.
"""

from __future__ import annotations

import pytest

from wasl.crawler.policy import (
    BATCH_PAGE_CAP,
    HARD_PAGE_CAP,
    INTERACTIVE_PAGE_CAP,
    MIN_REQUEST_INTERVAL_SECONDS,
    PROBE_PATHS,
    REQUESTS_PER_SECOND,
    Budget,
    CrawlPolicy,
    SeedRegistry,
    normalise_domain,
    total_request_estimate,
)

SEED_DATA = {
    "groups": {
        "test_group": {
            "label": "Test",
            "sites": [
                {"name": "Allowed Co", "url": "https://allowed.example", "golden": True},
                {"name": "Sub Co", "url": "https://uae.subdomain.example"},
                {"name": "Excluded Co", "url": "https://excluded.example"},
            ],
        }
    },
    "expected_counts": {"total_sites": 3, "golden_sites": 1, "groups": 1},
    "excluded": {
        "domains": ["excluded.example"],
        "reasons": {"excluded.example": "removal requested by the operator"},
    },
}


@pytest.fixture
def policy() -> CrawlPolicy:
    return CrawlPolicy(SeedRegistry(SEED_DATA))


# --- the limits are constants, not configuration -----------------------------


def test_rate_limit_is_half_a_request_per_second() -> None:
    assert REQUESTS_PER_SECOND == 0.5
    assert MIN_REQUEST_INTERVAL_SECONDS == 2.0


def test_page_caps_are_what_the_policy_promises() -> None:
    assert INTERACTIVE_PAGE_CAP == 12
    assert BATCH_PAGE_CAP == 40
    assert HARD_PAGE_CAP == 40


def test_no_budget_can_exceed_the_hard_cap(policy: CrawlPolicy) -> None:
    for budget in Budget:
        assert policy.page_cap(budget) <= HARD_PAGE_CAP


def test_request_estimate_counts_probes_not_just_pages() -> None:
    """The Phase 0 plan forgot this and understated the crawl by 20 seconds."""
    estimate = total_request_estimate(Budget.INTERACTIVE)
    assert estimate == INTERACTIVE_PAGE_CAP + len(PROBE_PATHS) + 1
    assert estimate > INTERACTIVE_PAGE_CAP


def test_throttle_floor_arithmetic() -> None:
    assert CrawlPolicy.throttle_seconds(12) == 24.0
    assert CrawlPolicy.throttle_seconds(40) == 80.0


# --- exclusion beats everything ----------------------------------------------


def test_exclusion_registry_beats_the_allowlist(policy: CrawlPolicy) -> None:
    """An opt-out an allowlist can override is not an opt-out."""
    decision = policy.check_domain("https://excluded.example")
    assert not decision.allowed
    assert decision.rule == "excluded"
    assert "removal requested" in decision.reason


def test_exclusion_beats_a_runtime_user_submission(policy: CrawlPolicy) -> None:
    """A user cannot re-enable a domain that asked to be removed."""
    decision = policy.check_domain("https://excluded.example", user_submitted=True)
    assert not decision.allowed
    assert decision.rule == "excluded"


# --- allowlist ---------------------------------------------------------------


def test_allowlisted_domain_is_permitted(policy: CrawlPolicy) -> None:
    assert policy.check_domain("https://allowed.example").allowed


def test_www_prefix_does_not_change_the_verdict(policy: CrawlPolicy) -> None:
    assert policy.check_domain("https://www.allowed.example").allowed


def test_unknown_domain_is_refused_by_default(policy: CrawlPolicy) -> None:
    decision = policy.check_domain("https://not-in-the-list.example")
    assert not decision.allowed
    assert decision.rule == "not_allowlisted"


def test_user_submission_bypasses_the_allowlist(policy: CrawlPolicy) -> None:
    """Scanning your own site is the product; it cannot require a seed entry."""
    decision = policy.check_domain("https://not-in-the-list.example", user_submitted=True)
    assert decision.allowed
    assert decision.rule == "user_submitted"


def test_subdomains_are_distinct_entries(policy: CrawlPolicy) -> None:
    """uae.sharafdg.com and sharafdg.com are different sites; do not merge them."""
    assert policy.check_domain("https://uae.subdomain.example").allowed
    assert not policy.check_domain("https://subdomain.example").allowed


# --- per-URL checks ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/checkout", "/cart", "/login", "/signin", "/register", "/account", "/payment", "/admin"],
)
def test_state_changing_paths_are_always_refused(policy: CrawlPolicy, path: str) -> None:
    decision = policy.check_url(f"https://allowed.example{path}")
    assert not decision.allowed
    assert decision.rule == "hard_excluded_path"


def test_hard_excluded_paths_match_on_segment_boundaries(policy: CrawlPolicy) -> None:
    """/accounts-payable is editorial content, not the account area."""
    assert policy.check_url("https://allowed.example/accounts-payable").allowed
    assert policy.check_url("https://allowed.example/cartography").allowed
    assert not policy.check_url("https://allowed.example/account/settings").allowed


def test_http_is_refused(policy: CrawlPolicy) -> None:
    assert policy.check_url("http://allowed.example/page").rule == "scheme"


@pytest.mark.parametrize("suffix", [".pdf", ".zip", ".mp4", ".jpg", ".woff2", ".exe"])
def test_binaries_and_assets_are_skipped(policy: CrawlPolicy, suffix: str) -> None:
    assert not policy.check_url(f"https://allowed.example/file{suffix}").allowed


def test_ordinary_content_urls_are_allowed(policy: CrawlPolicy) -> None:
    for url in [
        "https://allowed.example/",
        "https://allowed.example/product/12345",
        "https://allowed.example/search?q=valve",
    ]:
        assert policy.check_url(url).allowed, url


# --- registry ----------------------------------------------------------------


def test_registry_reports_actual_counts() -> None:
    registry = SeedRegistry(SEED_DATA)
    assert registry.actual_counts == {"total_sites": 3, "golden_sites": 1, "groups": 1}
    assert registry.golden_domains() == ["allowed.example"]


def test_real_seed_file_counts_match_what_it_declares() -> None:
    """Guards the 99-vs-101 class of error in the committed registry."""
    registry = SeedRegistry.load()
    assert registry.actual_counts == registry.expected_counts


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://www.Example.com/path", "example.com"),
        ("HTTPS://EXAMPLE.COM:8443", "example.com"),
        ("uae.example.com", "uae.example.com"),
        ("https://user@example.com", "example.com"),
    ],
)
def test_domain_normalisation(value: str, expected: str) -> None:
    assert normalise_domain(value) == expected
