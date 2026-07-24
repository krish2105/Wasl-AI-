"""Job queue, against a real Redis.

The interesting cases are the failure ones: a worker that dies holding a job, and
a worker shutting down gracefully. Both must return the job to the queue with its
ID intact, because the ID is what lets LangGraph resume from a checkpoint instead
of recrawling. Recrawling is not free — it means real requests to a real third
party who did not ask to be fetched twice.
"""

from __future__ import annotations

import pytest

from wasl.queue import (
    HEARTBEAT_KEY_PREFIX,
    PENDING_KEY,
    PROCESSING_KEY_PREFIX,
    JobQueue,
    QueuedJob,
)

pytestmark = pytest.mark.infra

JOB = QueuedJob(
    job_id="11111111-1111-1111-1111-111111111111",
    root_url="https://example.com",
    budget="interactive",
    submitted_by_user=True,
)


@pytest.fixture(autouse=True)
async def _clean_keys(queue: JobQueue, require_infra: None):
    async def purge() -> None:
        await queue._redis.delete(PENDING_KEY)
        async for key in queue._redis.scan_iter(match=f"{PROCESSING_KEY_PREFIX}*"):
            await queue._redis.delete(key)
        async for key in queue._redis.scan_iter(match=f"{HEARTBEAT_KEY_PREFIX}*"):
            await queue._redis.delete(key)

    await purge()
    yield
    await purge()


def test_queued_job_round_trips_through_json() -> None:
    assert QueuedJob.from_json(JOB.to_json()) == JOB


async def test_enqueue_then_dequeue_returns_the_same_job(queue: JobQueue) -> None:
    await queue.enqueue(JOB)
    assert await queue.depth() == 1

    picked = await queue.dequeue(timeout_seconds=2)

    assert picked == JOB
    assert await queue.depth() == 0


async def test_dequeue_returns_none_on_an_empty_queue(queue: JobQueue) -> None:
    assert await queue.dequeue(timeout_seconds=1) is None


async def test_jobs_come_back_in_the_order_they_went_in(queue: JobQueue) -> None:
    jobs = [
        QueuedJob(job_id=f"job-{i}", root_url="https://example.com", budget="batch",
                  submitted_by_user=False)
        for i in range(3)
    ]
    for job in jobs:
        await queue.enqueue(job)

    picked = [await queue.dequeue(timeout_seconds=2) for _ in jobs]

    assert [j.job_id for j in picked if j] == ["job-0", "job-1", "job-2"]


async def test_an_in_flight_job_is_recorded_on_the_processing_list(queue: JobQueue) -> None:
    """A job must never be in flight without being written down somewhere."""
    await queue.enqueue(JOB)
    await queue.dequeue(timeout_seconds=2)

    in_flight = await queue._redis.lrange(queue._processing_key, 0, -1)

    assert in_flight == [JOB.to_json()]


async def test_complete_clears_the_job_from_the_processing_list(queue: JobQueue) -> None:
    await queue.enqueue(JOB)
    picked = await queue.dequeue(timeout_seconds=2)
    assert picked is not None

    await queue.complete(picked)

    assert await queue._redis.llen(queue._processing_key) == 0
    assert await queue.depth() == 0


async def test_release_returns_an_unfinished_job_to_the_queue(queue: JobQueue) -> None:
    """Graceful shutdown must not lose work."""
    await queue.enqueue(JOB)
    picked = await queue.dequeue(timeout_seconds=2)
    assert picked is not None

    await queue.release(picked)

    assert await queue._redis.llen(queue._processing_key) == 0
    assert await queue.depth() == 1
    assert await queue.dequeue(timeout_seconds=2) == JOB


async def test_reclaim_returns_jobs_held_by_a_dead_worker(queue: JobQueue) -> None:
    """A worker that dies mid-scan must not strand its job forever."""
    dead = JobQueue(queue._redis, worker_name="worker-that-died")
    await dead.enqueue(JOB)
    await dead.dequeue(timeout_seconds=2)
    # Simulate the heartbeat expiring, which is what a crash looks like from here.
    await queue._redis.delete(f"{HEARTBEAT_KEY_PREFIX}{dead.worker_name}")

    reclaimed = await queue.reclaim_stale()

    assert reclaimed == 1
    assert await queue.depth() == 1


async def test_reclaim_leaves_a_live_worker_alone(queue: JobQueue) -> None:
    """Reclaiming from a healthy worker would run the same scan twice."""
    live = JobQueue(queue._redis, worker_name="worker-still-alive")
    await live.enqueue(JOB)
    await live.dequeue(timeout_seconds=2)  # dequeue writes a heartbeat

    reclaimed = await queue.reclaim_stale()

    assert reclaimed == 0
    assert await queue.depth() == 0


async def test_ping_succeeds_against_a_live_redis(queue: JobQueue) -> None:
    assert await queue.ping() is True
