from collections.abc import AsyncIterator, Callable, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from availability_engine.storage.memory import InMemoryStore
from availability_engine.storage.sql import models
from availability_engine.storage.sql.locking import attach_sqlite_begin_immediate
from availability_engine.storage.sql.store import SQLStore


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def sqlite_engine(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[AsyncEngine]:
    # A real temp-file path, NOT "sqlite+aiosqlite:///:memory:" — WAL mode
    # requires a real file on disk (CONTEXT.md's D-04), which supersedes
    # RESEARCH.md's illustrative :memory: code-example shorthand.
    db_path = tmp_path_factory.mktemp("sql") / "test.db"
    # NullPool so every checkout resolves to the one physical file (D-04:
    # "a single serialized connection").
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    attach_sqlite_begin_immediate(engine)
    async with engine.begin() as conn:
        await conn.run_sync(models.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    # Session-scoped, real testcontainers Postgres — started once for the
    # whole test session, torn down at session end (04-02-PLAN.md Task 1).
    with PostgresContainer("postgres:17", driver="asyncpg") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_engine(pg_container: PostgresContainer) -> AsyncIterator[AsyncEngine]:
    # metadata.create_all is already dialect-agnostic SQLAlchemy Core — no
    # dialect-specific creation logic needed, matching sqlite_engine's own
    # pattern.
    engine = create_async_engine(pg_container.get_connection_url())
    async with engine.begin() as conn:
        await conn.run_sync(models.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _reset_sql_tables(
    sqlite_engine: AsyncEngine, pg_engine: AsyncEngine
) -> None:
    # State does not leak across the 16+ parametrized contract_suite.py
    # methods the way a fresh InMemoryStore() naturally resets — both
    # session-scoped engines' tables must be explicitly emptied before each
    # test. reversed(metadata.sorted_tables) respects FK/dependency order.
    # A uniform table-delete reset across sqlite and postgres keeps the
    # isolation strategy identical for both rather than introducing a
    # second, more complex savepoint-rollback mechanism only for Postgres
    # (RESEARCH.md only recommends savepoint-rollback as a speed
    # optimization for contract_suite.py, not a correctness requirement).
    for engine in (sqlite_engine, pg_engine):
        async with engine.begin() as conn:
            for table in reversed(models.metadata.sorted_tables):
                await conn.execute(table.delete())


@pytest.fixture
def backend_factory(
    request: pytest.FixtureRequest, sqlite_engine: AsyncEngine, pg_engine: AsyncEngine
) -> Callable[[], InMemoryStore | SQLStore]:
    # pytest.mark.parametrize's static list can't close over a runtime
    # fixture value (sqlite_engine/pg_engine only exist after fixture
    # resolution), so contract_suite.py's parametrize is indirect — this
    # fixture reads request.param and returns the right zero-arg factory.
    # Every branch matches every existing contract_suite.py test body's
    # `backend = backend_factory()` call shape unchanged — the same SQLStore
    # class, same constructor shape, no Postgres-specific subclass or
    # special-casing needed.
    backend_id = request.param
    if backend_id == "in-memory":
        return InMemoryStore
    if backend_id == "sqlite":
        return lambda: SQLStore(sqlite_engine)
    if backend_id == "postgres":
        return lambda: SQLStore(pg_engine)
    raise ValueError(f"unknown backend_factory id: {backend_id!r}")
