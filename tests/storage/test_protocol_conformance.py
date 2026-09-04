"""StorageBackend Protocol structural-conformance test (STORE-01)."""

from sqlalchemy.ext.asyncio import AsyncEngine

from availability_engine.storage.memory import InMemoryStore
from availability_engine.storage.protocol import StorageBackend
from availability_engine.storage.sql.store import SQLStore


def test_inmemory_satisfies_protocol() -> None:
    assert isinstance(InMemoryStore(), StorageBackend)


def test_sqlstore_satisfies_protocol(sqlite_engine: AsyncEngine) -> None:
    assert isinstance(SQLStore(sqlite_engine), StorageBackend)
