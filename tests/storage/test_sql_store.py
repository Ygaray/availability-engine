"""Tracer test (Task 1, 04-01-PLAN.md): proves ONE real end-to-end
`place_hold` path (idempotency check, capacity gate, active-entries read,
error translation) works against a genuine SQL round-trip through SQLite,
not an in-memory dict.

Constructs `SQLStore(sqlite_engine)` directly, not yet through
`contract_suite.py`'s parametrize machinery — that wiring is Task 2.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from availability_engine.contracts import DEFAULT_BUSINESS_ID, Resource
from availability_engine.core.intervals import Interval
from availability_engine.errors import CapacityExhaustedError
from availability_engine.storage.sql.store import SQLStore


async def test_place_hold_end_to_end_sqlite(
    sqlite_engine: AsyncEngine, sample_resource: Resource
) -> None:
    store = SQLStore(sqlite_engine)
    await store.save_resource(sample_resource)
    slot = Interval(
        start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
        end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
    )

    hold = await store.place_hold(
        DEFAULT_BUSINESS_ID,
        sample_resource.id,
        slot,
        capacity=sample_resource.capacity,
        ttl_seconds=60,
    )

    assert hold.id
    assert hold.resource_id == sample_resource.id
    assert hold.slot_start == slot.start
    assert hold.slot_end == slot.end
    assert hold.expires_at > datetime.now(UTC)

    entries = await store.get_active_entries(
        DEFAULT_BUSINESS_ID, sample_resource.id, slot
    )
    assert hold in entries

    with pytest.raises(CapacityExhaustedError):
        await store.place_hold(
            DEFAULT_BUSINESS_ID,
            sample_resource.id,
            slot,
            capacity=sample_resource.capacity,
            ttl_seconds=60,
        )
