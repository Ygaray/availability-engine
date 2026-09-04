"""SQLAlchemy Core schema — one shared MetaData, four Table objects.

Mirrors the landed in-memory model's separate `_holds`/`_bookings` split
(CONTEXT.md Runtime Decisions, superseding D-02's original provisional
single-table draft) plus a distinct `idempotency` table keyed on
`(operation_type, key)`. Column names mirror `contracts.py`'s `Hold`/
`Booking` fields exactly — never invent different names (04-01-PLAN.md
Task 1).
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
    Column("id", String, primary_key=True),
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
)

holds = Table(
    "holds",
    metadata,
    Column("id", String, primary_key=True),
    Column("resource_id", String, nullable=False),
    Column("slot_start", DateTime(timezone=True), nullable=False),
    Column("slot_end", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Index("ix_holds_resource_slot", "resource_id", "slot_start"),
)

bookings = Table(
    "bookings",
    metadata,
    Column("id", String, primary_key=True),
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
    Index("ix_bookings_resource_slot_status", "resource_id", "slot_start", "status"),
)

idempotency = Table(
    "idempotency",
    metadata,
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
    # Composite primary key: a same-key race fails with a driver-level
    # unique-constraint violation rather than silently double-writing.
    PrimaryKeyConstraint("operation_type", "key"),
)

__all__ = ["metadata", "resources", "holds", "bookings", "idempotency"]
