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

from wasl.config import ConfigurationError, get_settings
from wasl.crawler.detectors import extract_all
from wasl.crawler.fetch import Crawler, CrawlRefused
from wasl.crawler.policy import Budget as CrawlBudget
from wasl.generators.packager import generate_all
from wasl.graph import events as ev
from wasl.graph.build import store_from_records
from wasl.graph.nodes import critic as critic_node
from wasl.graph.nodes import demo as demo_node
from wasl.graph.nodes import extract as extract_node
from wasl.graph.nodes import induce as induce_node
from wasl.graph.nodes import score as score_node
from wasl.graph.nodes import synthesize as synthesize_node
from wasl.graph.nodes.crawl import summarise
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


async def _load_pages(job: Job) -> tuple[list, Any, str | None]:
    """Get pages either from a fixture or from a real crawl.

    Returns (pages, artifacts, refusal reason). A refusal is not an exception —
    "this crawler is not configured to identify itself" is a legitimate and
    expected state that the UI needs to render clearly.
    """
    if job.source == "fixture":
        from wasl.scoring.cli import load_fixture, neutral_artifacts

        page = load_fixture(job.target)
        return [page], neutral_artifacts(page.final_url), None

    try:
        async with Crawler(budget=CrawlBudget.INTERACTIVE) as crawler:
            pages, artifacts = await crawler.crawl(job.target, user_submitted=True)
        return pages, artifacts, None
    except ConfigurationError as exc:
        return [], None, str(exc)
    except CrawlRefused as exc:
        return [], None, f"[{exc.rule}] {exc.reason}"


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

        # --- crawl -----------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "crawl"))
        pages, artifacts, refusal = await _load_pages(job)

        if refusal is not None:
            job.status = "refused"
            job.error = refusal
            await job.emit(ev.error(job.job_id, refusal, node="crawl"))
            await job.emit(ev.done(job.job_id, status="refused"))
            return

        for page in pages:
            await job.emit(
                ev.progress(
                    job.job_id,
                    "crawl",
                    page.final_url,
                    status=page.status_code,
                    robots_blocked=page.robots_blocked,
                    pre_js_chars=len(page.pre_js_html),
                    post_js_chars=len(page.post_js_html),
                )
            )
        await job.emit(ev.node_complete(job.job_id, "crawl", pages=len(pages)))

        state = WaslState(
            job_id=job.job_id,
            root_url=pages[0].final_url if pages else job.target,
            domain=artifacts.domain,
            pages=[summarise(p) for p in pages],
            user_submitted=True,
        )

        # --- extract ---------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "extract"))
        store = extract_all(pages, artifacts)
        state = state.model_copy(update={"evidence": extract_node.to_records(store)})

        for kind, count in store.kind_counts().items():
            await job.emit(ev.progress(job.job_id, "extract", kind, count=count))
        await job.emit(
            ev.node_complete(
                job.job_id, "extract", evidence=len(store), kinds=len(store.kind_counts())
            )
        )

        rebuilt = store_from_records(state.evidence)

        # --- induce ----------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "induce"))
        induced = await induce_node.induce(state, store=rebuilt, router=router)
        state = state.model_copy(
            update={"candidate_capabilities": induced.get("candidate_capabilities", [])}
        )
        for capability in state.candidate_capabilities:
            await job.emit(
                ev.ScanEvent(
                    type=ev.EventType.CAPABILITY,
                    job_id=job.job_id,
                    node="induce",
                    message=capability.name,
                    data={
                        "name": capability.name,
                        "verb": capability.verb,
                        "noun": capability.noun,
                        "evidence_ids": capability.evidence_ids,
                    },
                )
            )
        await job.emit(
            ev.node_complete(job.job_id, "induce", candidates=len(state.candidate_capabilities))
        )

        # --- synthesize ------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "synthesize"))
        synthesized = await synthesize_node.synthesize(state, store=rebuilt, router=router)
        state = state.model_copy(
            update={"candidate_capabilities": synthesized.get("candidate_capabilities", [])}
        )
        await job.emit(
            ev.node_complete(
                job.job_id,
                "synthesize",
                schemas=sum(1 for c in state.candidate_capabilities if c.tool_schema),
            )
        )

        # --- critic ----------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "critic"))
        critiqued = await critic_node.critique(state, store=rebuilt, router=router)
        state = state.model_copy(
            update={
                "accepted_capabilities": critiqued.get("accepted_capabilities", []),
                "rejections": critiqued.get("rejections", []),
            }
        )
        for rejection in state.rejections:
            await job.emit(
                ev.ScanEvent(
                    type=ev.EventType.REJECTION,
                    job_id=job.job_id,
                    node="critic",
                    message=rejection.capability_name,
                    data={"rule_id": rejection.rule_id, "reason": rejection.reason},
                )
            )
        await job.emit(
            ev.node_complete(
                job.job_id,
                "critic",
                accepted=len(state.accepted_capabilities),
                refused=len(state.rejections),
            )
        )

        # --- score -----------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "score"))
        scored = await score_node.score(state, store=rebuilt)
        state = state.model_copy(update={"score": scored.get("score")})
        await job.emit(
            ev.ScanEvent(
                type=ev.EventType.SCORE,
                job_id=job.job_id,
                node="score",
                data=state.score or {},
            )
        )
        await job.emit(ev.node_complete(job.job_id, "score"))

        # --- generate --------------------------------------------------------
        await job.emit(ev.node_start(job.job_id, "generate"))
        outcome = await generate_all(
            job_id=job.job_id,
            domain=artifacts.domain,
            site_name=artifacts.domain,
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
            raw_html=pages[0].pre_js_html if pages else "",
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


def create_job(*, target: str, source: Source) -> Job:
    job = Job(job_id=uuid.uuid4().hex[:12], target=target, source=source)
    _JOBS[job.job_id] = job
    return job


async def start_job(target: str, source: Source) -> Job:
    job = create_job(target=target, source=source)
    asyncio.create_task(run_job(job))
    return job
