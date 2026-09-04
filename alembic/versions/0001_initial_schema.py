"""Initial schema — resources, holds, bookings, idempotency.

The first commit's schema, mirroring
src/availability_engine/storage/sql/models.py's Table definitions exactly
(same column names, types, nullability, and indexes) — D-03: Alembic from
the first SQL commit, initial migration = current schema, even if trivial.

op.create_table itself needs no batch_alter_table wrapper — CREATE TABLE is
dialect-uniform SQL; batch mode (enabled globally via env.py's
render_as_batch=True) only matters starting with a future migration that
alters or drops a column (RESEARCH.md Code Examples).

Revision ID: 0001
Revises:
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from availability_engine.contracts import BookingStatus

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "definition",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "holds",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("slot_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_holds_resource_slot", "holds", ["resource_id", "slot_start"]
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("slot_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=BookingStatus.CONFIRMED.value,
        ),
    )
    op.create_index(
        "ix_bookings_resource_slot_status",
        "bookings",
        ["resource_id", "slot_start", "status"],
    )

    op.create_table(
        "idempotency",
        sa.Column("operation_type", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("result_type", sa.String(), nullable=False),
        sa.Column("result_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("operation_type", "key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency")
    op.drop_index("ix_bookings_resource_slot_status", table_name="bookings")
    op.drop_table("bookings")
    op.drop_index("ix_holds_resource_slot", table_name="holds")
    op.drop_table("holds")
    op.drop_table("resources")
