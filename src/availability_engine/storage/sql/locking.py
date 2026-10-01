"""The ONE dialect-branch point in the whole SQL backend (RESEARCH.md
Pattern 1). Every other query anywhere in `store.py` stays dialect-agnostic
SQLAlchemy Core.

**Supersedes CONTEXT.md's D-01.** D-01 ("defer `SELECT ... FOR UPDATE`,
rely solely on the atomic `INSERT ... SELECT ... WHERE (COUNT < capacity)`
conditional write") and the Runtime Decisions section's restated "Postgres
`SELECT ... FOR UPDATE`" are BOTH unsafe against genuinely concurrent
Postgres connections for this schema: `FOR UPDATE` cannot lock a row that
does not yet exist, so two concurrent transactions can both count zero
prior holds for an empty slot and both insert, overbooking capacity 1 to 2
(cybertec-postgresql.com's documented Postgres phantom-insert analysis,
04-01-PLAN.md RESEARCH.md). This module instead acquires a Postgres
transaction-scoped advisory lock (`pg_advisory_xact_lock`, keyed on
`(business_id, resource_id)` — see below) as the first statement of
`place_hold`'s transaction, auto-released on commit/rollback — a
schema-preserving, `READ COMMITTED`-preserving correction (D-04's isolation
level is untouched), not a new design. Wave 3's HOLD-02 concurrency test is
the empirical arbiter of this fix.

**26-07-PLAN.md Task 2 (D-05 widening):** the lock key dropped
`slot_start` and was keyed on resource_id alone — serializes ALL holds for
one resource, not just same-start-time ones, which is required once hold
start times are no longer confined to a fixed grid (D-04, Plan 26-08/26-10).
The ORIGINAL `(resource_id, slot_start)` key only serialized holds sharing
an identical `slot_start`, which was safe under the old fixed-grid design
but unsafe once start times can vary and overlap at different starts for
the same resource.

**26-09-PLAN.md Task 2 (closes review's MEDIUM "the advisory lock should
include business ID"):** widened FURTHER to `(business_id, resource_id)`
now that business_id is available at the storage layer — without this, two
different tenants' resources sharing a common id string like `"room-1"`
would serialize against each other unnecessarily. That is over-
serialization, not overbooking (RESEARCH.md Assumption A1, T-26-11), but is
worth closing now that the information exists.
"""

import weakref

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.pool import ConnectionPoolEntry


async def acquire_postgres_slot_lock(
    conn: AsyncConnection, business_id: str, resource_id: str
) -> None:
    """Acquire a transaction-scoped Postgres advisory lock keyed on
    `(business_id, resource_id)` — serializes ALL holds for one tenant's
    resource, not just same-start-time ones, which is required once hold
    start times are no longer confined to a fixed grid (D-04), and not
    across different tenants' resources that happen to share an id string
    (26-09-PLAN.md Task 2). Serializes concurrent `place_hold` (and only
    `place_hold` — see store.py's module docstring) attempts for the SAME
    tenant's resource without needing any pre-existing row to lock.
    Auto-released on commit/rollback — no leak risk even on a crashed
    connection.

    Never f-string-interpolate `business_id`/`resource_id` into SQL text
    (T-04-02 SQL-injection mitigation) — named bind parameters only. A rare
    `hashtext` collision between two different (business_id, resource_id)
    pairs would only ever over-serialize two unrelated resources, never
    cause overbooking (RESEARCH.md Assumption A1).
    """
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:bid), hashtext(:rid))"),
        {"bid": business_id, "rid": resource_id},
    )


# CR-02: a process-wide WeakSet of sync Engines that already have the
# listeners attached, so this function is safe to call more than once
# against the SAME physical engine. `SQLStore.__init__` now calls this
# automatically for every SQLStore constructed against a sqlite engine (see
# store.py) — since a single session-scoped engine commonly backs many
# SQLStore instances (e.g. one per test), re-registering the
# "connect"/"begin" listeners on every construction would stack duplicate
# listeners and issue `BEGIN IMMEDIATE` more than once per transaction,
# raising a driver error. A WeakSet (rather than an attribute on Engine,
# which SQLAlchemy's stubs don't expose for arbitrary extensibility) never
# outlives the engines it tracks.
_attached_engines: "weakref.WeakSet[Engine]" = weakref.WeakSet()


def attach_sqlite_begin_immediate(engine: AsyncEngine) -> None:
    """Register the two-event-listener recipe that gives SQLite a whole-
    database RESERVED write lock (BEGIN IMMEDIATE) for every transaction —
    phantom-safe by construction, no advisory-lock equivalent needed.

    - "connect": disable aiosqlite's implicit BEGIN (RESEARCH.md Pitfall 3)
      and set WAL mode + a 5s busy timeout (CONTEXT.md's D-04 explicit
      SQLite resolution).
    - "begin": issue BEGIN IMMEDIATE instead of the driver's default
      DEFERRED transaction.

    Idempotent per physical engine (see `_attached_engines` above) — safe
    to call multiple times (directly, and/or via `SQLStore.__init__`)
    against the same `AsyncEngine`.
    """
    sync_engine = engine.sync_engine
    if sync_engine in _attached_engines:
        return
    _attached_engines.add(sync_engine)

    @event.listens_for(sync_engine, "connect")
    def _do_connect(
        dbapi_connection: DBAPIConnection, connection_record: ConnectionPoolEntry
    ) -> None:
        # Disables aiosqlite's implicit BEGIN so our own explicit
        # BEGIN IMMEDIATE (below) is the one that actually takes effect.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(sync_engine, "begin")
    def _do_begin(conn: Connection) -> None:
        # Whole-database RESERVED write lock, phantom-safe by construction —
        # only ever one writer transaction on a SQLite file at a time under
        # this mode.
        conn.exec_driver_sql("BEGIN IMMEDIATE")


__all__ = ["acquire_postgres_slot_lock", "attach_sqlite_begin_immediate"]
