"""Durable checkpointing for the scan graph.

Why this exists rather than letting a failed scan start over: re-crawling is not
a local operation. A scan that dies at the critic and restarts from the top sends
a fresh set of requests to somebody else's server, at 0.5 req/s, for pages we
already have. The checkpointer is the difference between resuming at the critic
and apologising to a site operator.

`langgraph-checkpoint-postgres` is one of the two approved deviations from the
locked dependency list in CLAUDE.md §7, and it was added specifically for this.
It sat unimported until now, which meant the deviation had been approved for a
capability the code did not have.

Two decisions worth stating.

**A missing database degrades the scan, it does not fail it.** If Postgres is
unreachable the saver is None and the graph runs unresumably, exactly as it did
before this module existed. A scan that refuses to start because the *resume*
feature is unavailable would be a worse system than one without the feature. The
degradation is logged at WARNING so it appears in the trace rather than silently.

**The checkpointer's tables are created by its own `setup()`, not by Alembic.**
They belong to LangGraph and its migrations own their shape. Putting them in our
migration chain would mean hand-maintaining a third party's schema, and a version
bump would silently disagree with the database.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Small on purpose. Checkpoint writes are short and bursty, they share a database
# with the application pool, and a scan is not throughput-bound — it is bound by
# a 0.5 req/s crawl.
POOL_MAX_SIZE = 4

# Set by the application lifespan. Module-level rather than threaded through the
# call chain because the runner creates jobs from a background task with no
# request scope and therefore no access to app.state.
_ACTIVE: Any | None = None


def psycopg_dsn(database_url: str) -> str:
    """Convert a SQLAlchemy URL to one psycopg accepts.

    Settings carries `postgresql+psycopg://…` because SQLAlchemy needs the
    dialect suffix to pick a driver. psycopg itself rejects it. Same database,
    same credentials, two spellings — and getting this wrong surfaces as a
    connection error that reads like the database is down.
    """
    for dialect in ("postgresql+psycopg://", "postgresql+asyncpg://", "postgresql+psycopg2://"):
        if database_url.startswith(dialect):
            return "postgresql://" + database_url[len(dialect) :]
    return database_url


def _serializer() -> Any:
    """A serializer that will only rebuild our own state types from the database.

    LangGraph's default is permissive: it deserialises any type it finds and
    prints a deprecation warning. Its own docstring is blunt about the risk —
    "if an attacker can write directly to your checkpoint database, they may be
    able to trigger code execution when data is deserialized".

    That is not hypothetical here. Checkpoint rows contain crawled third-party
    content, which this project treats as untrusted everywhere else; it would be
    inconsistent to wrap it in `<untrusted_web_content>` on the way to a model
    and then hand the same database permissive deserialisation. The allowlist is
    also the forward fix: LangGraph has said it will block unregistered types in
    a later version, and a resume that stops working on a dependency bump would
    fail exactly when it is needed.

    Classes are passed rather than ("module", "Name") strings so a rename moves
    the allowlist with the code instead of silently orphaning an entry.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from wasl.graph import state as st

    return JsonPlusSerializer(
        allowed_msgpack_modules=[
            st.WaslState,
            st.PageSummary,
            st.EvidenceRecord,
            st.Capability,
            st.ToolSchema,
            st.Rejection,
            st.Finding,
            st.DemoResult,
            st.GeneratedArtifacts,
            st.Budget,
        ]
    )


@asynccontextmanager
async def open_checkpointer(
    database_url: str, *, connect_timeout: float = 5.0
) -> AsyncIterator[Any | None]:
    """Open a Postgres checkpointer for the lifetime of the application.

    Yields None if Postgres cannot be reached, having logged why. Callers must
    treat None as "resume is unavailable", never as an error.

    `connect_timeout` is generous by default because a container starting
    alongside the API may not be accepting connections yet, and giving up in
    under a second would disable resume for the common case of booting the
    whole stack at once.
    """
    global _ACTIVE

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool
    except ImportError as exc:  # pragma: no cover - the dependency is declared
        logger.warning("checkpointing unavailable, running unresumably: %s", exc)
        yield None
        return

    pool: Any | None = None
    try:
        pool = AsyncConnectionPool(
            conninfo=psycopg_dsn(database_url),
            max_size=POOL_MAX_SIZE,
            # autocommit is required by the saver's own setup(); prepare_threshold
            # is 0 because pgbouncer-style poolers reject prepared statements and
            # a hosted Postgres is the expected deployment.
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        await pool.open(wait=True, timeout=connect_timeout)

        saver = AsyncPostgresSaver(pool, serde=_serializer())
        await saver.setup()

        _ACTIVE = saver
        logger.info("graph checkpointing enabled")
        yield saver
    except Exception as exc:
        # Deliberately broad: an unreachable host, a refused connection, a wrong
        # password and a missing CREATE privilege are all the same outcome here,
        # which is that scans run without resume.
        logger.warning(
            "checkpointing disabled, scans will not be resumable: %s: %s",
            type(exc).__name__,
            exc,
        )
        yield None
    finally:
        _ACTIVE = None
        if pool is not None:
            try:
                await pool.close()
            except Exception:  # pragma: no cover - shutdown is best effort
                logger.debug("checkpoint pool close failed", exc_info=True)


def active_checkpointer() -> Any | None:
    """The checkpointer for this process, or None when resume is unavailable."""
    return _ACTIVE
