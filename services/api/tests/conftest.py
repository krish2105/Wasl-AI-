"""Shared test fixtures.

Tests that touch Postgres or Redis are marked `infra` and are skipped — loudly,
with the reason — when those services are not reachable. They are not mocked.
A mocked database test tells you your mock works.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv() -> None:
    """Populate os.environ from the repo-root .env, without overriding real vars."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "infra: requires postgres and redis (docker compose up -d)"
    )


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Settings are cached process-wide; tests that mutate env must start clean."""
    from wasl.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings():
    from wasl.config import get_settings

    return get_settings()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client bound directly to the ASGI app."""
    from wasl.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def queue() -> AsyncIterator["object"]:
    """A JobQueue on an isolated worker name, cleaned up after the test."""
    from wasl.queue import JobQueue

    q = JobQueue.from_settings(worker_name="pytest-worker")
    try:
        yield q
    finally:
        await q.close()


async def infra_available() -> tuple[bool, str]:
    """True when both Postgres and Redis answer."""
    from sqlalchemy import text

    from wasl.db.session import session_scope
    from wasl.queue import JobQueue

    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        return False, f"postgres unreachable: {type(exc).__name__}"

    q = JobQueue.from_settings()
    try:
        if not await q.ping():
            return False, "redis ping failed"
    except Exception as exc:
        return False, f"redis unreachable: {type(exc).__name__}"
    finally:
        await q.close()

    return True, ""


@pytest.fixture
async def require_infra() -> None:
    ok, reason = await infra_available()
    if not ok:
        pytest.skip(f"{reason} — run `docker compose up -d`")
