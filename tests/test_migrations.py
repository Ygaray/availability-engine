"""Migration-apply verification — STORE-05, Success Criterion #4.

Proves `alembic upgrade head` applies cleanly and identically against a
fresh SQLite file and a fresh Postgres database, each producing a schema
whose four tables (resources, holds, bookings, idempotency) match
src/availability_engine/storage/sql/models.py's metadata.

26-07-PLAN.md Task 3 additions: migration 0002's business_id backfill and
widened-PK proof against a fixture reproducing the LIVE escape-room
engine DB's exact pre-migration shape (not merely a fresh empty
database) — on both SQLite and Postgres.
"""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

EXPECTED_TABLES = {
    "resources",
    "holds",
    "bookings",
    "idempotency",
    "hold_business_index",
}

# The live escape-room engine DB's real resource ids (RAW, unprefixed —
# RESEARCH.md Open-Question-1, matching tests/availability/
# test_capacity_regression.py in this repo), used here to reproduce its
# exact pre-migration row shape rather than an arbitrary placeholder.
_LIVE_RESOURCE_IDS = ("cipher-vault", "lost-observatory")


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


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


async def _run_sync(sqlalchemy_url: str, fn):  # type: ignore[no-untyped-def]
    """Bridge an async Postgres connection into a sync callable — the same
    pattern `_inspect_table_names` uses above, generalized so Task 3's new
    tests can run arbitrary sync inspection/query code against Postgres.
    Read-only: uses `.connect()`, not `.begin()` — no write is committed.
    """
    async_engine = create_async_engine(sqlalchemy_url)
    try:
        async with async_engine.connect() as conn:
            return await conn.run_sync(fn)
    finally:
        await async_engine.dispose()


async def _run_sync_write(sqlalchemy_url: str, fn):  # type: ignore[no-untyped-def]
    """Same bridge as `_run_sync`, but via `.begin()` so a write `fn`
    performs (INSERT/UPDATE) is actually committed — 26-09-PLAN.md Task 1's
    Postgres backfill-proof test needs to seed rows, not just read them.
    """
    async_engine = create_async_engine(sqlalchemy_url)
    try:
        async with async_engine.begin() as conn:
            return await conn.run_sync(fn)
    finally:
        await async_engine.dispose()


def test_migration_0002_adds_business_id_on_fresh_sqlite_database(
    tmp_path: Path,
) -> None:
    """Test 1: a FRESH database needs no backfill — business_id is simply
    populated as given, proving the forward-only shape independent of the
    backfill logic.
    """
    db_path = tmp_path / "fresh.db"
    sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    cfg = _alembic_config(sqlalchemy_url)

    command.upgrade(cfg, "head")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO resources (id, business_id, definition) "
                    "VALUES ('cipher-vault', 'escaperoom', '{}')"
                )
            )
            row = conn.execute(sa.text("SELECT id, business_id FROM resources")).one()
        assert row == ("cipher-vault", "escaperoom")
    finally:
        sync_engine.dispose()


def test_migration_0002_backfills_preexisting_sqlite_rows_to_default(
    tmp_path: Path,
) -> None:
    """Test 2 (the real regression proof): apply 0001, manually insert rows
    shaped exactly like the LIVE escape-room engine DB's pre-migration rows
    (no business_id column, raw/unprefixed resource ids), then apply 0002.
    Every pre-existing row — resources, holds, AND idempotency — must be
    backfilled to business_id="default" (the generic sentinel, never a
    hardcoded consumer name), and both distinct resource rows must survive
    under the new composite PK.
    """
    db_path = tmp_path / "live_shaped.db"
    sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    cfg = _alembic_config(sqlalchemy_url)

    command.upgrade(cfg, "0001")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.begin() as conn:
            for resource_id in _LIVE_RESOURCE_IDS:
                conn.execute(
                    sa.text(
                        "INSERT INTO resources (id, definition) VALUES (:id, '{}')"
                    ),
                    {"id": resource_id},
                )
            conn.execute(
                sa.text(
                    "INSERT INTO holds "
                    "(id, resource_id, slot_start, slot_end, expires_at) "
                    "VALUES ('h1', :rid, '2026-01-01 00:00:00', "
                    "'2026-01-01 00:30:00', '2026-01-01 00:05:00')"
                ),
                {"rid": _LIVE_RESOURCE_IDS[0]},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO idempotency "
                    "(operation_type, key, fingerprint, result_type, result_id) "
                    "VALUES ('place_hold', 'k1', 'fp1', 'hold', 'h1')"
                )
            )
    finally:
        sync_engine.dispose()

    command.upgrade(cfg, "head")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.connect() as conn:
            resource_rows = dict(
                conn.execute(sa.text("SELECT id, business_id FROM resources")).all()
            )
            hold_business_id = conn.execute(
                sa.text("SELECT business_id FROM holds WHERE id = 'h1'")
            ).scalar_one()
            idem_business_id = conn.execute(
                sa.text(
                    "SELECT business_id FROM idempotency "
                    "WHERE operation_type = 'place_hold' AND key = 'k1'"
                )
            ).scalar_one()

        assert resource_rows == {rid: "default" for rid in _LIVE_RESOURCE_IDS}
        assert hold_business_id == "default"
        assert idem_business_id == "default"

        insp = sa.inspect(sync_engine)
        assert insp.get_pk_constraint("resources")["constrained_columns"] == [
            "business_id",
            "id",
        ]
        assert insp.get_pk_constraint("idempotency")["constrained_columns"] == [
            "business_id",
            "operation_type",
            "key",
        ]
    finally:
        sync_engine.dispose()


def test_migration_0002_downgrade_restores_0001_shape_sqlite(
    tmp_path: Path,
) -> None:
    """Test 3: downgrade() reverses 0002 cleanly back to 0001's column/
    index/PK shape on a fresh database (business_id VALUES are legitimately
    destroyed on downgrade, same as any migration's down path — not
    asserted here).
    """
    db_path = tmp_path / "roundtrip.db"
    sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    cfg = _alembic_config(sqlalchemy_url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        insp = sa.inspect(sync_engine)
        assert insp.get_pk_constraint("resources")["constrained_columns"] == ["id"]
        assert insp.get_pk_constraint("idempotency")["constrained_columns"] == [
            "operation_type",
            "key",
        ]
        assert "business_id" not in {c["name"] for c in insp.get_columns("resources")}
        assert "business_id" not in {c["name"] for c in insp.get_columns("holds")}
        assert "business_id" not in {c["name"] for c in insp.get_columns("bookings")}
        assert "business_id" not in {c["name"] for c in insp.get_columns("idempotency")}
        index_names = {ix["name"] for ix in insp.get_indexes("holds")}
        assert "ix_holds_resource_slot" in index_names
        assert "ix_holds_business_resource_slot" not in index_names
    finally:
        sync_engine.dispose()


def test_migration_0002_sqlite_pk_introspection_shows_only_new_pk(
    tmp_path: Path,
) -> None:
    """Test 5 (Cycle-2): direct schema introspection, not an inference from
    "the insert succeeded" — proves the OLD single/two-column PK is
    actually gone after 0002, not merely that the new composite columns
    also happen to accept inserts. Closes review's HIGH "SQLite primary-key
    replacement does not drop the old PK."
    """
    db_path = tmp_path / "pk_introspect.db"
    sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    cfg = _alembic_config(sqlalchemy_url)

    command.upgrade(cfg, "0001")
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO resources (id, definition) "
                    "VALUES ('cipher-vault', '{}')"
                )
            )
    finally:
        sync_engine.dispose()

    command.upgrade(cfg, "head")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        insp = sa.inspect(sync_engine)
        resources_pk = insp.get_pk_constraint("resources")
        idempotency_pk = insp.get_pk_constraint("idempotency")
        assert resources_pk["constrained_columns"] == ["business_id", "id"], (
            f"expected EXACTLY the new composite PK, got {resources_pk!r} — "
            "a leftover single-column PK alongside the new one would mean "
            "the old constraint was never actually dropped"
        )
        assert idempotency_pk["constrained_columns"] == [
            "business_id",
            "operation_type",
            "key",
        ], (
            f"expected EXACTLY the new composite PK, got {idempotency_pk!r} — "
            "a leftover 2-column PK alongside the new one would mean the "
            "old constraint was never actually dropped"
        )
    finally:
        sync_engine.dispose()


@pytest.mark.skipif(
    not _docker_available(),
    reason="Docker is not available — skipping the Postgres PK-drop proof",
)
def test_migration_0002_postgres_pk_drop_replaces_composite_primary_key() -> None:
    """Test 4 (Postgres PK-drop, dialect-branched): proves the
    `op.drop_constraint(..., type_="primary")` + `op.create_primary_key(...)`
    path — Postgres's own default implicit constraint name
    (`<table>_pkey`) for 0001's unnamed PKs — correctly replaces the
    single-column `resources` PK and the 2-column `idempotency` PK with
    their widened composites, not just SQLite's batch-table-recreate path.
    """
    with PostgresContainer("postgres:17", driver="asyncpg") as pg:
        sqlalchemy_url = pg.get_connection_url()
        cfg = _alembic_config(sqlalchemy_url)

        command.upgrade(cfg, "head")

        def _check_pks(sync_conn):  # type: ignore[no-untyped-def]
            insp = sa.inspect(sync_conn)
            return (
                insp.get_pk_constraint("resources"),
                insp.get_pk_constraint("idempotency"),
            )

        resources_pk, idempotency_pk = asyncio.run(
            _run_sync(sqlalchemy_url, _check_pks)
        )

    assert resources_pk["constrained_columns"] == ["business_id", "id"]
    assert idempotency_pk["constrained_columns"] == [
        "business_id",
        "operation_type",
        "key",
    ]


def test_migration_0003_adds_hold_business_index_on_fresh_sqlite_database(
    tmp_path: Path,
) -> None:
    """Forward shape: a fresh database just needs the table, no backfill —
    proven independent of the backfill proof below."""
    db_path = tmp_path / "fresh_0003.db"
    sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    cfg = _alembic_config(sqlalchemy_url)

    command.upgrade(cfg, "head")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        table_names = set(sa.inspect(sync_engine).get_table_names())
        assert "hold_business_index" in table_names
        pk = sa.inspect(sync_engine).get_pk_constraint("hold_business_index")
        assert pk["constrained_columns"] == ["hold_id"]
    finally:
        sync_engine.dispose()


def test_migration_0003_backfills_hold_business_index_for_preexisting_holds_sqlite(
    tmp_path: Path,
) -> None:
    """Resolved review concern (HIGH, max-cycles, independently
    source-verified in cycle 3): "migration 0003 populates
    hold_business_index only going forward with no backfill, so any hold
    surviving from v0.1 becomes unconfirmable after upgrade." Seeds a
    migration-0002-shaped SQLite file (business_id columns + widened PKs
    already in place) with a hold row inserted BEFORE 0003 runs — not a
    fresh database — then applies `alembic upgrade head` and asserts the
    pre-existing hold is present in hold_business_index afterward, resolved
    to its real (non-default) business_id. Without the backfill
    `INSERT ... SELECT` in 0003's upgrade(), this hold would be invisible
    to hold_business_index and confirm_hold would raise HoldNotFoundError
    for a hold that is still genuinely live in the `holds` table.
    """
    db_path = tmp_path / "preexisting_holds.db"
    sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    cfg = _alembic_config(sqlalchemy_url)

    command.upgrade(cfg, "0002")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO resources (id, business_id, definition) "
                    "VALUES ('cipher-vault', 'escaperoom', '{}')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO holds "
                    "(id, business_id, resource_id, slot_start, slot_end, "
                    "expires_at) VALUES ('pre-existing-hold', 'escaperoom', "
                    "'cipher-vault', '2026-01-01 00:00:00', "
                    "'2026-01-01 00:30:00', '2026-01-01 00:05:00')"
                )
            )
    finally:
        sync_engine.dispose()

    command.upgrade(cfg, "head")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.connect() as conn:
            business_id = conn.execute(
                sa.text(
                    "SELECT business_id FROM hold_business_index "
                    "WHERE hold_id = 'pre-existing-hold'"
                )
            ).scalar_one()
        assert business_id == "escaperoom", (
            "a hold that existed BEFORE migration 0003 ran must still be "
            "resolvable via hold_business_index after upgrade — a "
            "forward-only (no-backfill) index would strand this hold, "
            "making it unconfirmable post-upgrade"
        )
    finally:
        sync_engine.dispose()


@pytest.mark.skipif(
    not _docker_available(),
    reason="Docker is not available — skipping the Postgres backfill proof",
)
def test_migration_0003_backfills_hold_business_index_preexisting_holds_pg() -> None:
    """Postgres counterpart of the SQLite backfill proof above — the same
    pre-existing-hold-row shape, on the OTHER dialect this migration must
    also apply correctly against (op.create_table + a plain INSERT...SELECT
    are both dialect-uniform, but this closes the loop empirically rather
    than asserting it by code inspection alone)."""
    with PostgresContainer("postgres:17", driver="asyncpg") as pg:
        sqlalchemy_url = pg.get_connection_url()
        cfg = _alembic_config(sqlalchemy_url)

        command.upgrade(cfg, "0002")

        def _seed(sync_conn):  # type: ignore[no-untyped-def]
            sync_conn.execute(
                sa.text(
                    "INSERT INTO resources (id, business_id, definition) "
                    "VALUES ('cipher-vault', 'escaperoom', '{}')"
                )
            )
            sync_conn.execute(
                sa.text(
                    "INSERT INTO holds "
                    "(id, business_id, resource_id, slot_start, slot_end, "
                    "expires_at) VALUES ('pre-existing-hold', 'escaperoom', "
                    "'cipher-vault', '2026-01-01 00:00:00', "
                    "'2026-01-01 00:30:00', '2026-01-01 00:05:00')"
                )
            )

        asyncio.run(_run_sync_write(sqlalchemy_url, _seed))

        command.upgrade(cfg, "head")

        def _check(sync_conn):  # type: ignore[no-untyped-def]
            return sync_conn.execute(
                sa.text(
                    "SELECT business_id FROM hold_business_index "
                    "WHERE hold_id = 'pre-existing-hold'"
                )
            ).scalar_one()

        business_id = asyncio.run(_run_sync(sqlalchemy_url, _check))

    assert business_id == "escaperoom"


def test_migration_0003_downgrade_drops_hold_business_index_sqlite(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "roundtrip_0003.db"
    sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    cfg = _alembic_config(sqlalchemy_url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002")

    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        table_names = set(sa.inspect(sync_engine).get_table_names())
        assert "hold_business_index" not in table_names
    finally:
        sync_engine.dispose()
