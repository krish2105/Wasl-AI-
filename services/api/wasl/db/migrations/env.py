"""Alembic environment.

Runs migrations synchronously against the same DATABASE_URL the application uses
asynchronously. The driver prefix is normalised here so one environment variable
serves both — a copy-pasted Neon URL works without editing.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from wasl.config import load_settings
from wasl.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables LangGraph's Postgres checkpointer creates and owns via its own setup().
# They live in our database but not in our metadata, so autogenerate sees them as
# orphans and proposes DROP. Running that migration would delete every in-flight
# scan's resume state. Their schema belongs to a third party and its own
# migrations maintain it; ours must not touch them.
_FOREIGN_TABLES = frozenset(
    {
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    }
)


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    """Hide the checkpointer's tables from autogenerate and `alembic check`."""
    if type_ == "table":
        return name not in _FOREIGN_TABLES
    if type_ == "index" and parent_names.get("table_name") in _FOREIGN_TABLES:
        return False
    return True


def _sync_url() -> str:
    url = load_settings().database_url
    if url.startswith("postgresql+"):
        # Strip any async driver so alembic runs on the sync one.
        _, _, rest = url.partition("://")
        return f"postgresql+psycopg://{rest}"
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
