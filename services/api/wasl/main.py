"""FastAPI application: scan submission, live progress, reports, leaderboard.

Why the unimplemented routes return 501 rather than not existing: the API surface
is a design decision made in Phase 0, and writing it down where it will be
implemented is more useful than discovering it piecemeal later. Each one names
the phase that fills it in. None of them returns fabricated data — a stub that
answers with plausible-looking output is worse than no stub at all, because it
survives into a demo.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import text

from wasl import __version__
from wasl.config import get_settings
from wasl.db.session import dispose_engine, session_scope
from wasl.graph import runner
from wasl.graph.checkpoint import open_checkpointer
from wasl.obs.tracing import configure_tracing
from wasl.queue import JobQueue

logger = logging.getLogger(__name__)

NOT_IMPLEMENTED = status.HTTP_501_NOT_IMPLEMENTED


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    configure_tracing(settings)

    for directory in (settings.cache_dir, settings.artifacts_dir, settings.reference_dir):
        directory.mkdir(parents=True, exist_ok=True)

    queue = JobQueue.from_settings()
    app.state.queue = queue
    logger.info("wasl-api %s starting in %s", __version__, settings.env)

    # Opened for the process lifetime rather than per scan: setup() is a DDL
    # round trip and a pool per job would be worse than no pool. Yields None if
    # Postgres is unreachable, in which case scans still run, just unresumably.
    async with open_checkpointer(settings.database_url) as checkpointer:
        app.state.checkpointer = checkpointer
        try:
            yield
        finally:
            await queue.close()
            await dispose_engine()


app = FastAPI(
    title="Wasl AI",
    version=__version__,
    description=(
        "Scores whether a public website is legible to AI agents, and generates "
        "the MCP server that would make it legible."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Never "*": this API spends a real, rate-limited crawl budget against third
    # parties, and a wildcard lets any page on the internet spend it.
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- health ------------------------------------------------------------------


async def _check_database() -> tuple[bool, str]:
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _check_redis() -> tuple[bool, str]:
    queue = JobQueue.from_settings()
    try:
        return (True, "ok") if await queue.ping() else (False, "ping returned falsy")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await queue.close()


@app.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    """Liveness and dependency check.

    Reports 503 when a dependency is down rather than 200-with-a-warning. A
    health endpoint that stays green while Postgres is unreachable is worse than
    no health endpoint.
    """
    db_ok, db_detail = await _check_database()
    redis_ok, redis_detail = await _check_redis()
    settings = get_settings()

    healthy = db_ok and redis_ok
    body: dict[str, Any] = {
        "status": "ok" if healthy else "degraded",
        "version": __version__,
        "environment": settings.env,
        "checks": {
            "database": {"ok": db_ok, "detail": db_detail},
            "redis": {"ok": redis_ok, "detail": redis_detail},
        },
        # Surfaced because a deployment without it cannot legally crawl anything,
        # and that should be visible from the outside rather than discovered at
        # the first fetch.
        "crawler_identity_configured": bool(
            settings.crawler_info_url and settings.opt_out_email
        ),
        "playwright_available": settings.playwright_available,
    }
    return JSONResponse(
        content=body,
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# --- scan API ----------------------------------------------------------------

api = APIRouter(prefix="/api", tags=["scan"])

_PHASE_8 = "Implemented in Phase 8 (leaderboard)."


class ScanRequest(BaseModel):
    """Submit either a live URL or a saved fixture.

    Fixture mode exists because the crawler refuses to run without a configured
    identity, and the interface still needs to be exercisable end to end. Every
    model call, validator and critic rule is the production one; only the network
    is skipped, and the report says `source: fixture` so the distinction reaches
    the screen rather than living in a footnote.
    """

    model_config = {"extra": "forbid"}

    url: str | None = None
    fixture: str | None = None
    # Confirms the submitter understands the generated artifacts are
    # illustrative and unsigned. Without it, gate_pregenerate pauses the job
    # before anything is written for a domain they have not claimed.
    acknowledge_generation: bool = False

    @field_validator("url")
    @classmethod
    def _https_only(cls, v: str | None) -> str | None:
        if v and not v.startswith("https://"):
            raise ValueError("Only https URLs are crawled.")
        return v


@api.post("/scan", status_code=status.HTTP_202_ACCEPTED)
async def submit_scan(request: ScanRequest) -> JSONResponse:
    """Queue a scan. Policy and the crawler-identity check run inside the job."""
    if not request.url and not request.fixture:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Give either a url or a fixture name."},
        )

    job = await runner.start_job(
        target=request.fixture or request.url or "",
        acknowledged=request.acknowledge_generation,
        source="fixture" if request.fixture else "live",
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job_id": job.job_id, "source": job.source, "target": job.target},
    )


# response_model=None: FastAPI cannot derive a schema from a union of Response
# types, and there is nothing useful it could generate for an SSE stream anyway.
@api.get("/scan/{job_id}/events", response_model=None)
async def scan_events(job_id: str) -> StreamingResponse | JSONResponse:
    """Server-sent events: one per node, plus counters between them.

    Replays history first so a client that connects late — or reconnects — sees
    the whole run rather than joining midway.
    """
    job = runner.get_job(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"detail": f"No job {job_id}."})

    async def stream() -> AsyncIterator[str]:
        replayed = 0
        for event in list(job.history):
            replayed += 1
            yield event.to_sse()

        if job.status in {"complete", "failed", "refused"}:
            return

        while True:
            event = await job.queue.get()
            if event is None:
                break
            # Skip anything already replayed from history.
            if job.history.index(event) < replayed:
                continue
            yield event.to_sse()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@api.get("/scan/{job_id}")
async def scan_report(job_id: str) -> JSONResponse:
    """The full report: score, six axes, evidence, rejections, demo."""
    job = runner.get_job(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"detail": f"No job {job_id}."})

    if job.status in {"queued", "running"}:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"job_id": job_id, "status": job.status},
        )

    if job.report is None:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"job_id": job_id, "status": job.status, "detail": job.error},
        )

    return JSONResponse(content=job.report)


@api.get("/scan/{job_id}/artifacts.zip", response_model=None)
async def scan_artifacts(job_id: str) -> FileResponse | JSONResponse:
    """Download the generated bundle.

    Served only after the generated server imported in a clean subprocess and
    exposed at least one tool. An unverified artifact has no download path.
    """
    job = runner.get_job(job_id)
    if job is None or job.state is None or job.state.artifacts is None:
        return JSONResponse(status_code=404, content={"detail": f"No artifacts for {job_id}."})

    zip_path = job.state.artifacts.zip_path
    if not zip_path or not Path(zip_path).exists():
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Not offered for download: the generated server failed verification.",
                "verification": job.state.artifacts.verification_output,
            },
        )

    return FileResponse(zip_path, media_type="application/zip", filename=Path(zip_path).name)


@api.get("/leaderboard")
async def leaderboard() -> JSONResponse:
    """Seeded companies ranked by WARI. Government entities are anonymised."""
    return JSONResponse(status_code=NOT_IMPLEMENTED, content={"detail": _PHASE_8})


app.include_router(api)
