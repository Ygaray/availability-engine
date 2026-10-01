"""Add business_id to resources/holds/bookings, backfill, widen idempotency PK.

D-08/ENGINE-04 (26-07-PLAN.md Task 3): closes the confirmed global
cross-tenant idempotency-key collision that `ScopedAvailabilityPort`'s
client-side string-prefixing could never fully close. Adds a `business_id`
column to every table; widens `resources`' primary key to the composite
`(business_id, id)` (resource ids are caller-chosen strings — two tenants
choosing the identical id must coexist as two distinct rows) and
`idempotency`'s primary key to `(business_id, operation_type, key)` (the
actual fix this decision exists for). `holds`/`bookings` get a plain
`business_id` column (no PK change — their ids are engine-generated
`uuid4()` values, already globally unique) plus a business_id-leading
index replacing the old one.

Backfill value is the GENERIC sentinel `"default"` — the SAME value
`Resource.business_id` itself defaults to (Plan 26-06's
`Field(default="default")`) — NEVER a hardcoded consumer business name.
This is a reusable, domain-agnostic package (`pyproject.toml:4`); it must
not embed one consumer's identity in its own shipped migration. The
separate, consumer-owned reassignment of the live escape-room database's
rows away from this generic sentinel to that consumer's own real business
namespace is Plan 26-14's job (SocialNetwork-Chatbot repo), run once
after this migration has already applied and the live file has already
been backed up (Plan 26-13).

**Dialect-branch point #2 in this repo** (the first is
`storage/sql/locking.py`'s advisory lock, per that module's own
docstring): replacing an existing primary key is NOT dialect-uniform.

- On **Postgres**, the table is altered in place. 0001's unnamed
  single/two-column `PrimaryKeyConstraint` was assigned Postgres's own
  default implicit name (`<table>_pkey`) at CREATE TABLE time (confirmed
  by direct inspection against a live Postgres instance this round), so
  the old constraint is dropped by that name before the new composite one
  is created.
- On **SQLite**, the table is rebuilt via `op.batch_alter_table` (this
  repo's first ALTER-shaped migration, per `env.py`'s
  `render_as_batch=True`). Batch mode's own `create_primary_key(...)`
  call — issued inside the SAME batch context as the column add/backfill/
  not-null sequence — is what replaces the OLD (reflected, unnamed) PK:
  `ApplyBatchImpl.add_constraint()` evicts the existing primary key from
  the rebuilt table's constraint set whenever a NEW `PrimaryKeyConstraint`
  is added in the same batch, precisely because a table can only ever
  have one. **This migration deliberately does NOT call
  `batch_op.drop_constraint(None, type_="primary")` for this** — see the
  "Resolved review concerns" note in `26-07-SUMMARY.md` for why that
  exact call (recorded as the fix in this plan's Round-2 review ledger)
  is itself broken: Alembic's batch `drop_constraint` requires a
  constraint-name argument that is a real string (or its private
  `_NoneName` "explicitly unnamed" sentinel) — passing literal `None`
  builds a nameless dummy constraint object and `ApplyBatchImpl.
  drop_constraint` immediately raises `ValueError("Constraint must have
  a name")` on it, regardless of whether the REFLECTED table's own PK
  happens to be unnamed. Proven empirically against a real on-disk
  SQLite file seeded from 0001 (see `tests/test_migrations.py`); the
  `create_primary_key`-only path was proven correct the same way,
  including the explicit schema-introspection check
  (`get_pk_constraint`) that the OLD single-column PK is gone, not left
  behind alongside the new one.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _add_and_backfill_business_id(table_name: str) -> None:
    """Shared first half of every table's upgrade: add a NULLABLE
    business_id column (NOT NULL can't be added to a non-empty table
    without a server_default on either backend), then backfill every
    pre-existing row to the generic, package-level sentinel "default" —
    the SAME value `Resource.business_id` itself defaults to (Plan
    26-06's `Field(default="default")`). Never a hardcoded consumer
    business name.
    """
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(sa.Column("business_id", sa.String(), nullable=True))

    op.execute(
        sa.text(
            f"UPDATE {table_name} SET business_id = :bid WHERE business_id IS NULL"  # noqa: S608
        ).bindparams(bid="default")
    )


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # -- resources: business_id column + composite (business_id, id) PK --
    _add_and_backfill_business_id("resources")
    if is_postgres:
        with op.batch_alter_table("resources") as batch_op:
            batch_op.alter_column("business_id", nullable=False)
        # "resources_pkey" is Postgres's own default implicit constraint
        # name for 0001's unnamed single-column `primary_key=True` column.
        op.drop_constraint("resources_pkey", "resources", type_="primary")
        op.create_primary_key("pk_resources", "resources", ["business_id", "id"])
    else:
        with op.batch_alter_table("resources") as batch_op:
            batch_op.alter_column("business_id", nullable=False)
            # Replaces 0001's unnamed single-column PK in the SAME batch
            # table-recreate — no separate drop_constraint call needed or
            # possible for an unnamed reflected PK (see module docstring).
            batch_op.create_primary_key("pk_resources", ["business_id", "id"])

    # -- holds: business_id column only, no PK change, index renamed -----
    _add_and_backfill_business_id("holds")
    with op.batch_alter_table("holds") as batch_op:
        batch_op.alter_column("business_id", nullable=False)
    op.drop_index("ix_holds_resource_slot", table_name="holds")
    op.create_index(
        "ix_holds_business_resource_slot",
        "holds",
        ["business_id", "resource_id", "slot_start"],
    )

    # -- bookings: business_id column only, no PK change, index renamed --
    _add_and_backfill_business_id("bookings")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.alter_column("business_id", nullable=False)
    op.drop_index("ix_bookings_resource_slot_status", table_name="bookings")
    op.create_index(
        "ix_bookings_business_resource_slot_status",
        "bookings",
        ["business_id", "resource_id", "slot_start", "status"],
    )

    # -- idempotency: business_id column + composite 3-col PK ------------
    _add_and_backfill_business_id("idempotency")
    if is_postgres:
        with op.batch_alter_table("idempotency") as batch_op:
            batch_op.alter_column("business_id", nullable=False)
        # "idempotency_pkey" is Postgres's own default implicit constraint
        # name for 0001's unnamed `PrimaryKeyConstraint("operation_type",
        # "key")`.
        op.drop_constraint("idempotency_pkey", "idempotency", type_="primary")
        op.create_primary_key(
            "pk_idempotency", "idempotency", ["business_id", "operation_type", "key"]
        )
    else:
        with op.batch_alter_table("idempotency") as batch_op:
            batch_op.alter_column("business_id", nullable=False)
            batch_op.create_primary_key(
                "pk_idempotency", ["business_id", "operation_type", "key"]
            )


def downgrade() -> None:
    # Reverse-dependency order, mirroring 0001's own downgrade discipline:
    # idempotency, bookings, holds, resources.
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # -- idempotency: restore the 2-column (operation_type, key) PK ------
    if is_postgres:
        op.drop_constraint("pk_idempotency", "idempotency", type_="primary")
        op.create_primary_key(
            "idempotency_pkey", "idempotency", ["operation_type", "key"]
        )
        with op.batch_alter_table("idempotency") as batch_op:
            batch_op.drop_column("business_id")
    else:
        # Dropping business_id (a member of the live composite PK)
        # narrows the rebuilt table's PK back to the remaining columns
        # automatically — no explicit create_primary_key needed. Proven
        # empirically against a real on-disk SQLite file (see
        # tests/test_migrations.py).
        with op.batch_alter_table("idempotency") as batch_op:
            batch_op.drop_column("business_id")

    # -- bookings: restore the original index, drop business_id ----------
    op.drop_index("ix_bookings_business_resource_slot_status", table_name="bookings")
    op.create_index(
        "ix_bookings_resource_slot_status",
        "bookings",
        ["resource_id", "slot_start", "status"],
    )
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("business_id")

    # -- holds: restore the original index, drop business_id -------------
    op.drop_index("ix_holds_business_resource_slot", table_name="holds")
    op.create_index("ix_holds_resource_slot", "holds", ["resource_id", "slot_start"])
    with op.batch_alter_table("holds") as batch_op:
        batch_op.drop_column("business_id")

    # -- resources: restore the single-column `id` PK --------------------
    if is_postgres:
        op.drop_constraint("pk_resources", "resources", type_="primary")
        op.create_primary_key("resources_pkey", "resources", ["id"])
        with op.batch_alter_table("resources") as batch_op:
            batch_op.drop_column("business_id")
    else:
        with op.batch_alter_table("resources") as batch_op:
            batch_op.drop_column("business_id")
