"""Redis-backed job queue.

Why hand-rolled rather than Celery/RQ/arq: the durability problem those libraries
solve is already solved elsewhere in this system. LangGraph checkpoints every
node transition to Postgres, so a scan that dies mid-run resumes from its last
completed node regardless of what the queue remembers. That leaves the queue with
one job — hand out work exactly once, and notice when a worker dies holding a
job — which is about a hundred lines of Redis and zero new dependencies.

The reliable-queue pattern here is the standard one: `BLMOVE` atomically pops
from the pending list and pushes onto a per-worker processing list, so a job is
never in flight without being recorded somewhere. A crashed worker leaves its job
on its processing list, where `reclaim_stale()` finds it.
"""

from __future__ import annotations

import json
import logging
import socket
import time
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from wasl.config import get_settings

logger = logging.getLogger(__name__)

PENDING_KEY = "wasl:jobs:pending"
PROCESSING_KEY_PREFIX = "wasl:jobs:processing:"
HEARTBEAT_KEY_PREFIX = "wasl:worker:heartbeat:"

# A worker that has not touched its heartbeat in this long is presumed dead and
# its in-flight jobs are returned to the pending list.
WORKER_HEARTBEAT_TTL_SECONDS = 120


@dataclass(frozen=True, slots=True)
class QueuedJob:
    """A unit of work handed to a worker."""

    job_id: str
    root_url: str
    budget: str
    submitted_by_user: bool

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "root_url": self.root_url,
                "budget": self.budget,
                "submitted_by_user": self.submitted_by_user,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> QueuedJob:
        data: dict[str, Any] = json.loads(raw)
        return cls(
            job_id=data["job_id"],
            root_url=data["root_url"],
            budget=data.get("budget", "interactive"),
            submitted_by_user=bool(data.get("submitted_by_user", False)),
        )


def _default_worker_name() -> str:
    return f"{socket.gethostname()}:{time.time_ns()}"


class JobQueue:
    """Reliable FIFO queue over a Redis list."""

    def __init__(self, redis: Redis, *, worker_name: str | None = None) -> None:
        self._redis = redis
        self.worker_name = worker_name or _default_worker_name()

    @classmethod
    def from_settings(cls, *, worker_name: str | None = None) -> JobQueue:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        return cls(redis, worker_name=worker_name)

    @property
    def _processing_key(self) -> str:
        return f"{PROCESSING_KEY_PREFIX}{self.worker_name}"

    async def ping(self) -> bool:
        """True if Redis answers. Used by the health endpoint."""
        try:
            return bool(await self._redis.ping())
        except Exception:
            logger.warning("Redis ping failed", exc_info=True)
            return False

    async def enqueue(self, job: QueuedJob) -> int:
        """Add a job to the back of the queue. Returns the new queue depth."""
        return int(await self._redis.lpush(PENDING_KEY, job.to_json()))

    async def depth(self) -> int:
        """Number of jobs waiting to be picked up."""
        return int(await self._redis.llen(PENDING_KEY))

    async def dequeue(self, *, timeout_seconds: int = 5) -> QueuedJob | None:
        """Block for a job, moving it atomically onto this worker's in-flight list.

        Returns None on timeout so the caller can run its own housekeeping
        between polls rather than blocking forever.
        """
        raw = await self._redis.blmove(
            PENDING_KEY,
            self._processing_key,
            timeout=timeout_seconds,
            src="RIGHT",
            dest="LEFT",
        )
        if raw is None:
            return None
        await self.heartbeat()
        return QueuedJob.from_json(raw)

    async def complete(self, job: QueuedJob) -> None:
        """Remove a finished job from this worker's in-flight list."""
        await self._redis.lrem(self._processing_key, 1, job.to_json())

    async def release(self, job: QueuedJob) -> None:
        """Return an unfinished job to the pending queue.

        Used on graceful shutdown. The job keeps its ID, so LangGraph resumes it
        from its last checkpoint rather than recrawling from scratch — which
        matters, because recrawling means real requests to a real third party.
        """
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self._processing_key, 1, job.to_json())
            pipe.lpush(PENDING_KEY, job.to_json())
            await pipe.execute()

    async def heartbeat(self) -> None:
        """Record that this worker is alive."""
        await self._redis.set(
            f"{HEARTBEAT_KEY_PREFIX}{self.worker_name}",
            str(time.time()),
            ex=WORKER_HEARTBEAT_TTL_SECONDS,
        )

    async def reclaim_stale(self) -> int:
        """Return jobs held by dead workers to the pending queue.

        A worker's heartbeat key expires on its own; its processing list does
        not. Any processing list without a live heartbeat belonged to a worker
        that died, so its jobs go back.
        """
        reclaimed = 0
        async for key in self._redis.scan_iter(match=f"{PROCESSING_KEY_PREFIX}*"):
            worker = key[len(PROCESSING_KEY_PREFIX) :]
            if await self._redis.exists(f"{HEARTBEAT_KEY_PREFIX}{worker}"):
                continue
            while (raw := await self._redis.rpop(key)) is not None:
                await self._redis.lpush(PENDING_KEY, raw)
                reclaimed += 1
            if reclaimed:
                logger.info("Reclaimed %d job(s) from dead worker %s", reclaimed, worker)
        return reclaimed

    async def close(self) -> None:
        await self._redis.aclose()
