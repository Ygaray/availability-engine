from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from availability_engine.storage.sql import models
from availability_engine.storage.sql.locking import attach_sqlite_begin_immediate


@pytest_asyncio.fixture(scope="session")
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
