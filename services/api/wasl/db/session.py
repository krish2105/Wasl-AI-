"""Async engine and session factory.

Why async: a scan spends almost all of its wall-clock waiting — on a rate-limited
fetch, on a model call, on a page to finish hydrating. Blocking a worker thread
through any of that would cap concurrency at something absurd.

`psycopg` v3 is used in async mode, which is why the URL carries the
`postgresql+psycopg` driver prefix. Alembic runs the same URL synchronously; the
translation happens in `migrations/env.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wasl.config import get_settings


def _async_url(url: str) -> str:
    """Normalise a DATABASE_URL onto the async psycopg driver.

    Accepts the bare `postgresql://` form that hosted providers hand out, as well
    as the explicit `postgresql+psycopg://` form, so a copy-pasted Neon URL works
    without editing.
    """
    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Process-wide async engine."""
    settings = get_settings()
    return create_async_engine(
        _async_url(settings.database_url),
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Process-wide session factory."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session. Commits on clean exit, rolls back on exception."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session."""
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    """Close pooled connections. Called on application shutdown."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
