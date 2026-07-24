"""Per-domain rate limiting, correct across multiple workers.

Why Redis and a Lua script rather than an in-process `asyncio.Semaphore`: the
limit that matters is "requests this domain receives", not "requests this process
sends". Two workers each politely waiting 2 seconds locally deliver one request
per second to the site, which is double what we promised. The reservation has to
be shared, and it has to be atomic — a read-then-write from two workers races and
both conclude they may go now.

The script reserves the *next* slot rather than checking whether the current one
is free. Each caller walks the queue forward by one interval and is told how long
to wait for the slot it just took, so N concurrent callers serialise cleanly
instead of stampeding.

If a site's robots.txt asks for a longer delay than ours, we honour theirs. We
never honour a shorter one.
"""

from __future__ import annotations

import asyncio
import logging
import time

from redis.asyncio import Redis

from wasl.crawler.policy import MIN_REQUEST_INTERVAL_SECONDS, normalise_domain
from wasl.config import get_settings

logger = logging.getLogger(__name__)

RATE_KEY_PREFIX = "wasl:ratelimit:"

# Keys expire well after the longest plausible gap between two requests to the
# same domain, so a stale reservation never blocks a later crawl.
_KEY_TTL_SECONDS = 3600

# KEYS[1] = domain key, ARGV[1] = now, ARGV[2] = interval.
# Returns the number of seconds the caller must wait for the slot it reserved.
_RESERVE_SLOT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local interval = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

local next_free = tonumber(redis.call('GET', key) or '0')
local slot = now
if next_free > now then
  slot = next_free
end

redis.call('SET', key, slot + interval, 'EX', ttl)
return tostring(slot - now)
"""


class DomainRateLimiter:
    """Reserves request slots so a domain never sees more than one per interval."""

    def __init__(self, redis: Redis, *, interval_seconds: float | None = None) -> None:
        self._redis = redis
        # Floor, never a ceiling. A caller cannot ask to go faster than policy.
        self._interval = max(
            MIN_REQUEST_INTERVAL_SECONDS, interval_seconds or MIN_REQUEST_INTERVAL_SECONDS
        )
        self._script = redis.register_script(_RESERVE_SLOT)

    @classmethod
    def from_settings(cls, *, interval_seconds: float | None = None) -> DomainRateLimiter:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        return cls(redis, interval_seconds=interval_seconds)

    @property
    def interval_seconds(self) -> float:
        return self._interval

    def with_crawl_delay(self, crawl_delay: float | None) -> DomainRateLimiter:
        """A limiter honouring a site's own Crawl-delay when it is stricter."""
        if crawl_delay is None or crawl_delay <= self._interval:
            return self
        logger.info("Honouring robots.txt Crawl-delay of %.1fs", crawl_delay)
        return DomainRateLimiter(self._redis, interval_seconds=crawl_delay)

    async def reserve(self, domain_or_url: str) -> float:
        """Reserve the next slot for a domain. Returns the seconds to wait.

        Does not sleep — `acquire()` does. Separated so a dry run can report the
        wait without incurring it.
        """
        domain = normalise_domain(domain_or_url)
        key = f"{RATE_KEY_PREFIX}{domain}"
        raw = await self._script(
            keys=[key], args=[repr(time.time()), repr(self._interval), _KEY_TTL_SECONDS]
        )
        return max(0.0, float(raw))

    async def acquire(self, domain_or_url: str) -> float:
        """Block until this caller's reserved slot arrives. Returns seconds waited."""
        wait = await self.reserve(domain_or_url)
        if wait > 0:
            await asyncio.sleep(wait)
        return wait

    async def reset(self, domain_or_url: str) -> None:
        """Clear a domain's reservation. Tests only — never called by the crawler."""
        await self._redis.delete(f"{RATE_KEY_PREFIX}{normalise_domain(domain_or_url)}")

    async def close(self) -> None:
        await self._redis.aclose()
