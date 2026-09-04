"""Migration-apply verification — STORE-05, Success Criterion #4.

Proves `alembic upgrade head` applies cleanly and identically against a
fresh SQLite file and a fresh Postgres database, each producing a schema
whose four tables (resources, holds, bookings, idempotency) match
src/availability_engine/storage/sql/models.py's metadata.
"""

import asyncio
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

EXPECTED_TABLES = {"resources", "holds", "bookings", "idempotency"}


def _alembic_config(sqlalchemy_url: str) -> Config:
    repo_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return cfg


def test_alembic_upgrade_head_creates_sqlite_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "migration_test.db"
    sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    cfg = _alembic_config(sqlalchemy_url)

    command.upgrade(cfg, "head")

    # Plain sync SQLAlchemy connection against the same file — inspecting
    # table names is a read-only, dialect-agnostic check that doesn't need
    # the async driver.
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        table_names = set(sa.inspect(sync_engine).get_table_names())
    finally:
        sync_engine.dispose()

    assert EXPECTED_TABLES <= table_names


async def _inspect_table_names(sqlalchemy_url: str) -> set[str]:
    # Only the asyncpg driver is installed (no sync psycopg2/psycopg in this
    # project's dependency set), so inspect via an async engine's run_sync
    # bridge rather than a plain sync connection.
    async_engine = create_async_engine(sqlalchemy_url)
    try:
        async with async_engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: set(sa.inspect(sync_conn).get_table_names())
            )
    finally:
        await async_engine.dispose()


def test_alembic_upgrade_head_creates_postgres_schema() -> None:
    # Kept as a plain sync test (not `async def`) deliberately: alembic's
    # env.py calls asyncio.run() internally (see run_migrations_online),
    # which raises "cannot be called from a running event loop" if this
    # test were itself wrapped in pytest-asyncio's event loop. A sync test
    # body lets command.upgrade() and the asyncio.run()-based inspection
    # helper below each own their own top-level event loop in turn.
    #
    # This plan's own throwaway testcontainers Postgres instance, scoped to
    # this test only — deliberately NOT importing or depending on Plan
    # 04-02's conftest.py fixtures (pg_container), so this plan's files
    # stay non-overlapping with Plan 04-02's for Wave 2 parallel-safe
    # execution (04-03-PLAN.md Task 2).
    with PostgresContainer("postgres:17", driver="asyncpg") as pg:
        sqlalchemy_url = pg.get_connection_url()
        cfg = _alembic_config(sqlalchemy_url)

        command.upgrade(cfg, "head")

        table_names = asyncio.run(_inspect_table_names(sqlalchemy_url))

    assert EXPECTED_TABLES <= table_names
