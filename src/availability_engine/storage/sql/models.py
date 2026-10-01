"""SQLAlchemy Core schema — one shared MetaData, four Table objects.

Mirrors the landed in-memory model's separate `_holds`/`_bookings` split
(CONTEXT.md Runtime Decisions, superseding D-02's original provisional
single-table draft) plus a distinct `idempotency` table keyed on
`(business_id, operation_type, key)`. Column names mirror `contracts.py`'s
`Hold`/`Booking` fields exactly — never invent different names
(04-01-PLAN.md Task 1).

D-08/ENGINE-04 (26-07-PLAN.md Task 1): every table now carries a
`business_id` column, closing the confirmed global cross-tenant
idempotency-key collision that `ScopedAvailabilityPort`'s client-side
string-prefixing could never fully close on its own. `resources`' primary
key widens to the composite `(business_id, id)` — resource ids are
caller-chosen strings (e.g. `"cipher-vault"`), so two tenants independently
choosing the identical id must coexist as two distinct rows, not collide on
a single-column PK. `holds`/`bookings` gain a plain `business_id` column
(no PK change — their ids are engine-generated `uuid4()` values, already
globally unique regardless of tenant; business_id there is for
query-scoping/indexing only). `idempotency`'s primary key widens to the
3-column composite `(business_id, operation_type, key)` — the actual fix
this decision exists for.

Deviation (Rule 3, 26-07-PLAN.md Task 1 — not in the plan's literal action
text): each `business_id` column carries a client-side `default="default"`
— the SAME generic sentinel `Resource.business_id` itself defaults to
(Plan 26-06) and migration 0002's own backfill value. Without it, every
existing SQLAlchemy Core `insert(...)` call site in `store.py` (none of
which pass `business_id` — threading it through the storage layer is Plan
26-09's job) would violate the new NOT NULL constraint, breaking
`tests/storage/test_sql_store.py` and
`tests/storage/test_protocol_conformance.py`, which Task 2's own `<verify>`
re-runs and expects green. The default keeps this plan's schema-only scope
self-consistent without pulling Plan 26-09's business_id-threading work
forward.
"""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    func,
)
from sqlalchemy.dialects import postgresql

from availability_engine.contracts import BookingStatus

metadata = MetaData()

resources = Table(
    "resources",
    metadata,
    Column("id", String, nullable=False),
    Column("business_id", String, nullable=False, default="default"),
    # The full Resource stored via Resource.model_dump(mode="json"),
    # reconstructed via Resource.model_validate on read (Claude's Discretion
    # per CONTEXT.md — no gray area named a resources schema).
    Column(
        "definition",
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=False,
    ),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    # Composite PK (D-08/ENGINE-04): resource ids are caller-chosen strings,
    # so two tenants choosing the identical id must coexist as two distinct
    # rows rather than collide on a single-column PK.
    PrimaryKeyConstraint("business_id", "id"),
)

holds = Table(
    "holds",
    metadata,
    Column("id", String, primary_key=True),
    Column("business_id", String, nullable=False, default="default"),
    Column("resource_id", String, nullable=False),
    Column("slot_start", DateTime(timezone=True), nullable=False),
    Column("slot_end", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Index(
        "ix_holds_business_resource_slot", "business_id", "resource_id", "slot_start"
    ),
)

bookings = Table(
    "bookings",
    metadata,
    Column("id", String, primary_key=True),
    Column("business_id", String, nullable=False, default="default"),
    Column("resource_id", String, nullable=False),
    Column("slot_start", DateTime(timezone=True), nullable=False),
    Column("slot_end", DateTime(timezone=True), nullable=False),
    # Postgres gets JSONB, SQLite gets generic JSON from the same column
    # definition (04-01-PLAN.md Task 1).
    Column(
        "payload",
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=False,
    ),
    Column(
        "status",
        String,
        nullable=False,
        default=BookingStatus.CONFIRMED.value,
        server_default=BookingStatus.CONFIRMED.value,
    ),
    Index(
        "ix_bookings_business_resource_slot_status",
        "business_id",
        "resource_id",
        "slot_start",
        "status",
    ),
)

idempotency = Table(
    "idempotency",
    metadata,
    Column("business_id", String, nullable=False, default="default"),
    Column("operation_type", String, nullable=False),
    Column("key", String, nullable=False),
    Column("fingerprint", String, nullable=False),
    # "hold" or "booking" — which table `result_id` references.
    Column("result_type", String, nullable=False),
    Column("result_id", String, nullable=False),
    # Present now even though no reaper runs yet (RESEARCH.md Security
    # Domain retention note, CONTEXT.md Runtime Decisions) — a future
    # retention policy does not require a migration to add this column.
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    # Composite primary key, business_id-leading (D-08/ENGINE-04): a
    # same-key race fails with a driver-level unique-constraint violation
    # rather than silently double-writing, AND two different tenants
    # independently choosing the identical (operation_type, key) pair never
    # collide — closing the confirmed global cross-tenant idempotency-key
    # collision.
    PrimaryKeyConstraint("business_id", "operation_type", "key"),
)

hold_business_index = Table(
    "hold_business_index",
    metadata,
    # 26-09-PLAN.md Task 1 (closes review's HIGH "confirm replay cannot
    # derive the tenant from the hold row"): a PERMANENT, never-deleted
    # hold_id -> business_id index. confirm_hold resolves its tenant from
    # here BEFORE the idempotency check and BEFORE any `holds` row lookup —
    # a successful prior confirm_hold already DELETES the `holds` row, so a
    # replay (same idempotency_key, second call) would find no hold row at
    # all if business_id were derived from that row instead. This table's
    # own row for a given hold_id is NEVER deleted by confirm_hold,
    # release_hold, or any future expiry reaper — it exists solely so a
    # bare hold_id can always be resolved to its owning tenant, even long
    # after the hold itself is gone. Migration 0003 backfills this table
    # for every pre-existing hold row (not just holds placed going
    # forward) by copying `holds.business_id`, which migration 0002
    # already backfilled onto every such row — so a hold that existed
    # before this migration remains confirmable/cancelable after upgrade.
    #
    # Retention policy (LOW review concern, "no retention strategy —
    # grows unbounded"): deliberately retained for the life of the
    # process/database, not just the life of the hold row — that is the
    # entire point of this table (a confirm replay must work even after
    # the hold row is gone). Growth is bounded by the total number of
    # holds EVER placed (two short string columns per row), the same
    # unbounded-but-small-footprint shape `idempotency` already has today
    # with no reaper (see that table's own comment above) — accepted as a
    # deliberate, documented risk for v1 scope rather than a silent gap. A
    # future retention policy (e.g. pruning entries once the corresponding
    # confirm_hold idempotency record itself ages out) is deferred until
    # an actual operational cost is observed, exactly like idempotency's
    # own deferred-reaper note.
    Column("hold_id", String, primary_key=True),
    Column("business_id", String, nullable=False),
)

__all__ = [
    "metadata",
    "resources",
    "holds",
    "bookings",
    "idempotency",
    "hold_business_index",
]
