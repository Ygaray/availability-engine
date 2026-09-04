"""Alembic migration environment — async engine + batch mode (STORE-05).

Consumer-run rather than auto-applied on import (D-03 — a library does not
own a runtime lifecycle): nothing in this module runs a migration at import
time. A consumer (or this repo's own tests) explicitly invokes
`alembic.command.upgrade(cfg, "head")` or the `alembic` CLI.

target_metadata is imported directly from
src/availability_engine/storage/sql/models.py — the exact same MetaData
object store.py's engine uses for metadata.create_all in test fixtures.
Never hand-copy or redeclare the table definitions here (04-03-PLAN.md
Task 1 key_link) — a second, hand-copied MetaData would let migrations and
the live schema drift apart silently.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool
from sqlalchemy.ext.asyncio import create_async_engine

from availability_engine.storage.sql.models import metadata

# Alembic Config object, providing access to values within alembic.ini.
config = context.config

# Interpret the config file for Python logging (only if present — the
# programmatic Config objects the test suite builds don't set a
# config_file_name).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The single shared MetaData object — see module docstring.
target_metadata = metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Safe on Postgres too — batch mode only actually activates when
        # SQLite's limited ALTER support requires it (RESEARCH.md Code
        # Examples, Pitfall 4's cited alembic.sqlalchemy.org/en/latest/batch.html).
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """Run migrations in 'online' mode against an async engine.

    Builds create_async_engine from the configured sqlalchemy.url, bridges
    into Alembic's synchronous migration runner via connection.run_sync,
    then disposes the engine.
    """
    configuration = config.get_section(config.config_ini_section) or {}
    url = config.get_main_option("sqlalchemy.url")
    if url is not None:
        configuration["sqlalchemy.url"] = url

    connectable = create_async_engine(
        configuration.get("sqlalchemy.url", ""),
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Dispatches to the async bridge above unless the configured URL is a
    sync-only dialect (kept as a fallback for engine_from_config-style
    tooling that might not use an async driver URL).
    """
    url = config.get_main_option("sqlalchemy.url") or ""
    if "+asyncpg" in url or "+aiosqlite" in url or url == "":
        asyncio.run(run_migrations_online_async())
        return

    # Fallback: a plain sync DBAPI URL was supplied — run migrations via a
    # sync engine directly (kept for completeness; every URL this repo's
    # own tests and consumers use is async per the locked storage protocol).
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
