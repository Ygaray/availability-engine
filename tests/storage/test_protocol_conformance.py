"""StorageBackend Protocol structural-conformance test (STORE-01)."""

from availability_engine.storage.memory import InMemoryStore
from availability_engine.storage.protocol import StorageBackend


def test_inmemory_satisfies_protocol() -> None:
    assert isinstance(InMemoryStore(), StorageBackend)
