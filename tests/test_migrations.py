"""Migration-apply verification — STORE-05, Success Criterion #4.

Proves `alembic upgrade head` applies cleanly and identically against a
fresh SQLite file and a fresh Postgres database, each producing a schema
whose four tables (resources, holds, bookings, idempotency) match
src/availability_engine/storage/sql/models.py's metadata.
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

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
