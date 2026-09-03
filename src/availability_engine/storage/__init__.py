"""Storage backends: the async StorageBackend Protocol plus the shipped
reference/test implementation.

`InMemoryStore` is re-exported here (in addition to its home module
`availability_engine.storage.memory`) so consumers prototyping or testing
against this library don't need to know the specific module path.
"""

from availability_engine.storage.memory import InMemoryStore

__all__ = ["InMemoryStore"]
