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
from typing import Any

from fastapi import APIRouter, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from wasl import __version__
from wasl.config import get_settings
from wasl.db.session import dispose_engine, session_scope
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
    allow_origins=["http://localhost:3000"],
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

_PHASE_4 = "Implemented in Phase 4 (LangGraph agents)."
_PHASE_5 = "Implemented in Phase 5 (generators and probe)."
_PHASE_8 = "Implemented in Phase 8 (leaderboard)."


def _not_implemented(detail: str) -> JSONResponse:
    return JSONResponse(status_code=NOT_IMPLEMENTED, content={"detail": detail})


@api.post("/scan", status_code=NOT_IMPLEMENTED)
async def submit_scan() -> JSONResponse:
    """Queue a scan of a URL. Enforces the allowlist and the pre-crawl gate."""
    return _not_implemented(_PHASE_4)


@api.get("/scan/{job_id}/events")
async def scan_events(job_id: str) -> JSONResponse:
    """Server-sent events: one per LangGraph node, plus evidence counters."""
    return _not_implemented(_PHASE_4)


@api.get("/scan/{job_id}")
async def scan_report(job_id: str) -> JSONResponse:
    """The full report: WARI score, six axes, evidence refs, critic rejections."""
    return _not_implemented(_PHASE_4)


@api.get("/scan/{job_id}/artifacts.zip")
async def scan_artifacts(job_id: str) -> JSONResponse:
    """Download the generated MCP server, Agent Card and llms.txt.

    Only served after the generated server has been imported in a clean
    subprocess and its tools introspected.
    """
    return _not_implemented(_PHASE_5)


@api.get("/leaderboard")
async def leaderboard() -> JSONResponse:
    """Seeded companies ranked by WARI. Government entities are anonymised."""
    return _not_implemented(_PHASE_8)


app.include_router(api)
