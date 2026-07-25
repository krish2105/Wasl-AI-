"""Runs a scan and streams what it is doing.

The pipeline already exists as nodes; this wraps it so a browser can watch. Two
things it deliberately does not do:

**It does not batch.** Events are pushed as each node starts and finishes, and
progress ticks between them. A UI that receives everything at the end cannot
show a system thinking, and the streaming build-up is most of what makes the
scan feel real rather than staged.

**It does not hide the source.** A scan run against a saved fixture is labelled
`fixture` in its own report, all the way to the UI. Every model call, validator
and critic rule is the production one — only the network is skipped — but that
distinction belongs on screen, not in a footnote.

Jobs live in memory. Single process, no persistence across restarts: the durable
record is the LangGraph checkpoint and the artifacts on disk, and building a
second job store on top of those would be inventing a problem.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from wasl.config import get_settings
from wasl.crawler.cache import SnapshotCache
from wasl.generators.packager import generate_all
from wasl.graph import events as ev
from wasl.graph.build import build_graph, gate_pregenerate, store_from_records
from wasl.graph.checkpoint import active_checkpointer
from wasl.graph.nodes import demo as demo_node
from wasl.graph.state import WaslState
from wasl.llm.router import ModelRouter

logger = logging.getLogger(__name__)

Source = Literal["live", "fixture"]
Status = Literal["queued", "running", "complete", "failed", "refused"]


@dataclass
class Job:
    """One scan, its event stream, and its result."""

    job_id: str
    target: str
    source: Source
    status: Status = "queued"
    # Set when the submitter has confirmed they understand the generated
    # artifacts are illustrative and unsigned. Drives gate_pregenerate.
    acknowledged: bool = False
    queue: asyncio.Queue[ev.ScanEvent | None] = field(default_factory=asyncio.Queue)
    history: list[ev.ScanEvent] = field(default_factory=list)
    state: WaslState | None = None
    report: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    seconds: float = 0.0

    async def emit(self, event: ev.ScanEvent) -> None:
        self.history.append(event)
        await self.queue.put(event)

    async def close(self) -> None:
        await self.queue.put(None)


_JOBS: dict[str, Job] = {}


def get_job(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def all_jobs() -> list[Job]:
    return list(_JOBS.values())


def _raw_sample(state: WaslState) -> str:
    """The raw pre-JS body the demo's first arm reads.

    Re-read rather than carried through state. The graph deliberately keeps
    captured pages out of `WaslState` so a checkpoint stays small, and the demo
    is the only consumer left that needs the bytes. A fixture reloads from disk;
    a live scan reads the snapshot the crawl already wrote, so neither path sends
    a second request.
    """
    if state.source == "fixture":
        from wasl.scoring.cli import load_fixture

        try:
            return load_fixture(state.root_url).pre_js_html
        except Exception:  # pragma: no cover - the demo degrades, it does not fail
            logger.debug("fixture reload for demo failed", exc_info=True)
            return ""

    page = SnapshotCache().latest(state.root_url)
    return page.pre_js_html if page else ""


async def run_job(job: Job) -> None:
    """Execute the whole pipeline, emitting events as it goes."""
    router = ModelRouter()
    started = time.perf_counter()
    job.status = "running"

    try:
        await job.emit(
            ev.ScanEvent(
                type=ev.EventType.JOB_START,
                job_id=job.job_id,
                message=f"Scanning {job.target}",
                data={
                    "target": job.target,
                    "source": job.source,
                    "nodes": [{"id": n, "label": l} for n, l in ev.NODE_SEQUENCE],
                },
            )
        )

        # --- the graph -------------------------------------------------------
        # gate_precrawl through score runs as the compiled LangGraph. That is
        # what makes the pre-crawl gate real rather than declared, and what makes
        # a checkpointed resume possible. Progress events reach the client from
        # inside the nodes, through the run config, so a 12-page crawl at
        # 0.5 req/s still ticks rather than going silent for 24 seconds.
        # None when Postgres is unreachable: the scan runs, it just cannot be
        # resumed. Never a reason to refuse to start.
        graph = build_graph(router, checkpointer=active_checkpointer())
        config = {"configurable": {"thread_id": job.job_id, "emit": job.emit}}
        raw_state = await graph.ainvoke(
            WaslState(
                job_id=job.job_id,
                root_url=job.target,
                source=job.source,
                user_submitted=job.source != "fixture",
            ),
            config,
        )
        state = raw_state if isinstance(raw_state, WaslState) else WaslState(**raw_state)

        if state.awaiting_confirmation or (state.errors and not state.pages):
            reason = state.awaiting_confirmation or state.errors[0]
            job.status = "refused"
            job.error = reason
            job.state = state
            await job.emit(ev.done(job.job_id, status="refused"))
            return

        rebuilt = store_from_records(state.evidence)

        # --- gate_pregenerate ------------------------------------------------
        # Blocking, per CLAUDE.md §6. Scanning somebody else's site is fine;
        # writing an MCP server that purports to describe their business is the
        # thing that needs a human behind it, so the pause sits here and not
        # earlier. A fixture is our own saved page and passes straight through.
        confirmation = gate_pregenerate(state, owns_domain=job.acknowledged)
        if confirmation is not None:
            job.status = "awaiting_confirmation"
            job.error = confirmation
            job.state = state
            job.seconds = time.perf_counter() - started
            await job.emit(ev.error(job.job_id, confirmation, node="generate"))
            await job.emit(ev.done(job.job_id, status="awaiting_confirmation"))
            return

        # --- generate --------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "generate"))
        outcome = await generate_all(
            job_id=job.job_id,
            domain=state.domain,
            site_name=state.domain,
            capabilities=[*state.accepted_capabilities, *state.candidate_capabilities],
            pages=state.pages,
            store=rebuilt,
            score=state.score,
            output_root=get_settings().artifacts_dir,
        )
        state = state.model_copy(update={"artifacts": outcome.artifacts})
        await job.emit(
            ev.ScanEvent(
                type=ev.EventType.ARTIFACT,
                job_id=job.job_id,
                node="generate",
                message=outcome.verification.summary().splitlines()[0],
                data={
                    "verified": outcome.verification.ships,
                    "tool_count": outcome.verification.tool_count,
                    "downloadable": bool(outcome.artifacts.zip_path),
                },
            )
        )
        await job.emit(ev.node_complete(job.job_id, "generate"))

        # --- demo ------------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "demo"))
        demo = await demo_node.run_demo(
            state,
            store=rebuilt,
            raw_html=_raw_sample(state),
            router=router,
        )
        state = state.model_copy(update={"demo_result": demo.get("demo_result")})
        await job.emit(
            ev.ScanEvent(
                type=ev.EventType.DEMO,
                job_id=job.job_id,
                node="demo",
                data={
                    "raw_succeeded": state.demo_result.raw_succeeded if state.demo_result else False,
                    "mcp_succeeded": state.demo_result.mcp_succeeded if state.demo_result else False,
                },
            )
        )
        await job.emit(ev.node_complete(job.job_id, "demo"))

        job.state = state
        job.seconds = time.perf_counter() - started
        # Status before report: build_report snapshots it, and a report that says
        # "running" after the run finished is confusing in exactly the place a
        # user is looking for reassurance that it did.
        job.status = "complete"
        job.report = build_report(job, store=rebuilt, verification=outcome)

        await job.emit(
            ev.done(
                job.job_id,
                status="complete",
                seconds=round(job.seconds, 1),
                model_calls=router.usage.calls,
                cost_usd=router.usage.cost_usd,
            )
        )

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("job %s failed", job.job_id)
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        await job.emit(ev.error(job.job_id, job.error))
        await job.emit(ev.done(job.job_id, status="failed"))
    finally:
        await job.close()


def build_report(job: Job, *, store, verification) -> dict[str, Any]:
    """The full report the UI renders. Evidence is included so the drawer can open."""
    state = job.state
    assert state is not None

    return {
        "job_id": job.job_id,
        "target": job.target,
        "domain": state.domain,
        "source": job.source,
        "status": job.status,
        "seconds": round(job.seconds, 1),
        "score": state.score,
        "pages": [p.model_dump() for p in state.pages],
        "evidence": [
            {
                "id": e.id,
                "kind": e.kind,
                "source_url": e.source_url,
                "selector": e.selector,
                "raw": e.raw,
                "phase": e.phase,
            }
            for e in store
        ],
        "accepted_capabilities": [c.model_dump() for c in state.accepted_capabilities],
        "rejections": [r.model_dump() for r in state.rejections],
        "findings": [f.model_dump() for f in state.security_findings],
        "demo": state.demo_result.model_dump() if state.demo_result else None,
        "artifacts": {
            "verified": verification.verification.ships,
            "tool_count": verification.verification.tool_count,
            "summary": verification.verification.summary(),
            "downloadable": bool(verification.artifacts.zip_path),
        },
        "errors": state.errors,
    }


def create_job(*, target: str, source: Source, acknowledged: bool = False) -> Job:
    job = Job(
        job_id=uuid.uuid4().hex[:12],
        target=target,
        source=source,
        acknowledged=acknowledged,
    )
    _JOBS[job.job_id] = job
    return job


async def start_job(target: str, source: Source, acknowledged: bool = False) -> Job:
    job = create_job(target=target, source=source, acknowledged=acknowledged)
    asyncio.create_task(run_job(job))
    return job
