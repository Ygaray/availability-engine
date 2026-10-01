"""Add hold_business_index, backfilled from every pre-existing hold row.

D-A / 26-09-PLAN.md Task 1 Cycle-2 correction (closes review's HIGH "confirm
replay cannot derive the tenant from the hold row"): `confirm_hold`'s
idempotency check must run BEFORE any `holds` row lookup, because a
successful prior confirm_hold already DELETES the `holds` row — a replay
(same idempotency_key, second call) would find no hold row to derive
`business_id` from. This migration adds a PERMANENT, never-deleted
`hold_id -> business_id` index that `confirm_hold` resolves its tenant from
instead, before the idempotency check and before any `holds` row lookup.

**Resolved review concern (HIGH, max-cycles, independently source-verified
in cycle 3): "migration 0003 populates hold_business_index only going
forward with no backfill, so any hold surviving from v0.1 becomes
unconfirmable after upgrade."** A forward-only, empty-at-creation
`hold_business_index` would indeed strand every hold that was already
`INSERT`ed into `holds` before this migration ran — `confirm_hold` would
look up `hold_business_index` first, find nothing, and raise
`HoldNotFoundError` for a hold that is still genuinely live and sitting in
the `holds` table. Root cause: a naive reading of "index populated by
place_hold going forward" assumes every row in `holds` was inserted by a
POST-migration `place_hold` call, which is false for any hold that
survives an upgrade mid-flight (any hold whose TTL has not yet elapsed at
the moment this migration runs).

Fix: after creating the table, backfill it by copying `(id, business_id)`
from every row already present in `holds` — migration 0002 already
guaranteed every `holds` row (pre-existing or not) carries an authoritative
`business_id` column (backfilled to the generic `"default"` sentinel for
any row that predates 0002 too), so this single `INSERT ... SELECT` is a
complete, exact backfill with no join or derivation needed beyond the
column 0002 already put in place. A hold that existed before this
migration therefore remains confirmable/cancelable after upgrade — proven
by `tests/test_migrations.py`'s
`test_migration_0003_backfills_hold_business_index_for_preexisting_holds_sqlite`
(and its Postgres counterpart), which seed a migration-0002-shaped database
with a hold row inserted BEFORE 0003 runs, apply `alembic upgrade head`,
and assert the row is present and correctly resolvable via
`hold_business_index` afterward — not merely a fresh-database test.

**Resolved review concern (LOW, actionable): "hold_business_index has no
retention strategy and grows unbounded."** Documented, accepted policy —
see `src/availability_engine/storage/sql/models.py`'s `hold_business_index`
Table comment for the full rationale: this table is deliberately retained
for the life of the database (not just the life of the hold row), since a
confirm replay must resolve a hold's tenant even after the hold itself is
long gone. Growth is bounded by total holds ever placed, two short string
columns per row — the same unbounded-but-small-footprint shape the
`idempotency` table already has today with no reaper. No cleanup mechanism
is introduced in this migration; this is an explicit, accepted risk for v1
scope, not a silent gap.

`op.create_table` is dialect-uniform SQL (CREATE TABLE needs no
`batch_alter_table` wrapper, matching 0001's own note) — this is NOT an
ALTER/column-add migration like 0002, so no per-dialect branching is
needed here at all.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hold_business_index",
        sa.Column("hold_id", sa.String(), primary_key=True),
        sa.Column("business_id", sa.String(), nullable=False),
    )

    # Backfill: every hold that existed before this migration already
    # carries an authoritative business_id column (added and backfilled by
    # migration 0002) — copy it straight across so a confirm_hold on a
    # pre-existing hold can resolve its tenant from this new permanent
    # index immediately, not just for holds placed after this migration.
    op.execute(
        sa.text(
            "INSERT INTO hold_business_index (hold_id, business_id) "
            "SELECT id, business_id FROM holds"
        )
    )


def downgrade() -> None:
    op.drop_table("hold_business_index")
