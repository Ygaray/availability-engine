"""SQL storage backend (SQLAlchemy Core, SQLite + Postgres) — Phase 4."""

from availability_engine.storage.sql.locking import (
    acquire_postgres_slot_lock,
    attach_sqlite_begin_immediate,
)
from availability_engine.storage.sql.models import metadata
from availability_engine.storage.sql.store import SQLStore

__all__ = [
    "SQLStore",
    "acquire_postgres_slot_lock",
    "attach_sqlite_begin_immediate",
    "metadata",
]
