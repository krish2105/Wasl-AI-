"""Per-domain rate limiter, against real Redis.

The test that matters is the concurrent one. An in-process limiter passes a
single-caller test easily and still lets two workers deliver double the promised
rate to a site — which is the actual failure mode, and the reason this is
implemented as an atomic Redis reservation rather than a local sleep.
"""

from __future__ import annotations

import asyncio

import pytest
from redis.asyncio import Redis

from wasl.config import get_settings
from wasl.crawler.policy import MIN_REQUEST_INTERVAL_SECONDS
from wasl.crawler.ratelimit import DomainRateLimiter

pytestmark = pytest.mark.infra

DOMAIN = "ratelimit-test.example"


@pytest.fixture
async def limiter(require_infra: None):
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    limiter = DomainRateLimiter(redis)
    await limiter.reset(DOMAIN)
    try:
        yield limiter
    finally:
        await limiter.reset(DOMAIN)
        await limiter.close()


async def test_the_first_request_to_a_domain_does_not_wait(limiter: DomainRateLimiter) -> None:
    assert await limiter.reserve(DOMAIN) == pytest.approx(0.0, abs=0.05)


async def test_the_second_request_waits_a_full_interval(limiter: DomainRateLimiter) -> None:
    await limiter.reserve(DOMAIN)
    assert await limiter.reserve(DOMAIN) == pytest.approx(MIN_REQUEST_INTERVAL_SECONDS, abs=0.1)


async def test_reservations_queue_rather_than_collide(limiter: DomainRateLimiter) -> None:
    """Each caller takes the next slot, so N callers serialise instead of stampeding."""
    waits = [await limiter.reserve(DOMAIN) for _ in range(4)]
    expected = [i * MIN_REQUEST_INTERVAL_SECONDS for i in range(4)]
    assert waits == pytest.approx(expected, abs=0.1)


async def test_concurrent_workers_share_one_budget(limiter: DomainRateLimiter) -> None:
    """The limit is 'requests this domain receives', not 'requests one process sends'."""
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    others = [DomainRateLimiter(redis) for _ in range(3)]
    try:
        waits = await asyncio.gather(
            limiter.reserve(DOMAIN), *(other.reserve(DOMAIN) for other in others)
        )
        # Four separate limiter instances, one shared queue: 0s, 2s, 4s, 6s.
        assert sorted(waits) == pytest.approx(
            [i * MIN_REQUEST_INTERVAL_SECONDS for i in range(4)], abs=0.15
        )
    finally:
        await redis.aclose()


async def test_different_domains_do_not_block_each_other(limiter: DomainRateLimiter) -> None:
    await limiter.reserve("a.example")
    assert await limiter.reserve("b.example") == pytest.approx(0.0, abs=0.05)
    await limiter.reset("a.example")
    await limiter.reset("b.example")


async def test_www_and_bare_domain_share_a_budget(limiter: DomainRateLimiter) -> None:
    """Otherwise a crawl doubles its rate by alternating hostnames."""
    await limiter.reserve(f"https://www.{DOMAIN}/a")
    wait = await limiter.reserve(f"https://{DOMAIN}/b")
    assert wait == pytest.approx(MIN_REQUEST_INTERVAL_SECONDS, abs=0.1)


async def test_a_longer_crawl_delay_is_honoured(limiter: DomainRateLimiter) -> None:
    stricter = limiter.with_crawl_delay(10.0)
    assert stricter.interval_seconds == 10.0


async def test_a_shorter_crawl_delay_is_ignored(limiter: DomainRateLimiter) -> None:
    """A site asking us to go faster than our own floor does not get to."""
    assert limiter.with_crawl_delay(0.1) is limiter
    assert limiter.interval_seconds == MIN_REQUEST_INTERVAL_SECONDS


async def test_the_interval_cannot_be_configured_below_policy(require_infra: None) -> None:
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        assert DomainRateLimiter(redis, interval_seconds=0.01).interval_seconds == (
            MIN_REQUEST_INTERVAL_SECONDS
        )
    finally:
        await redis.aclose()


async def test_acquire_actually_sleeps(limiter: DomainRateLimiter) -> None:
    loop = asyncio.get_running_loop()
    await limiter.acquire(DOMAIN)
    started = loop.time()
    waited = await limiter.acquire(DOMAIN)
    elapsed = loop.time() - started

    assert waited == pytest.approx(MIN_REQUEST_INTERVAL_SECONDS, abs=0.1)
    assert elapsed >= MIN_REQUEST_INTERVAL_SECONDS - 0.1
