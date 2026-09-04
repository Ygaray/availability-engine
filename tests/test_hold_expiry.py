"""Lazy hold-expiry end-to-end test (AVAIL-03, HOLD-05).

Drives the full `AvailabilityEngine` facade over a fresh `InMemoryStore` (not
the storage layer directly) to prove:

1. An unexpired hold blocks a second hold on the same capacity-1 slot
   (`CapacityExhaustedError`) — this already passes today, proving the
   harness is correct before testing the fix below.
2. After the first hold's TTL elapses, with NO explicit `release_hold` or
   `confirm_hold` call, a second hold on the same slot succeeds — this FAILS
   against the unfixed `InMemoryStore` (neither `get_active_entries` nor
   `_count_active` filters by `hold.expires_at`) and must pass once
   `get_active_entries` becomes the one shared, expiry-filtering primitive.

No production code is modified by this file.
"""

from datetime import UTC, datetime, timedelta

import pytest
import time_machine

from availability_engine.contracts import Resource
from availability_engine.engine import AvailabilityEngine
from availability_engine.errors import CapacityExhaustedError
from availability_engine.storage.memory import InMemoryStore

_T0 = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


async def test_active_hold_blocks_second_hold_while_unexpired(
    sample_resource: Resource,
) -> None:
    store = InMemoryStore()
    engine = AvailabilityEngine(store)
    await engine.define_resource(sample_resource)
    slot_start = _T0 + timedelta(hours=1)
    slot_end = slot_start + timedelta(minutes=30)

    with time_machine.travel(_T0, tick=False):
        await engine.place_hold(
            sample_resource.id, slot_start, slot_end, ttl_seconds=60
        )

        with pytest.raises(CapacityExhaustedError):
            await engine.place_hold(
                sample_resource.id, slot_start, slot_end, ttl_seconds=60
            )


async def test_expired_hold_stops_blocking_capacity_with_no_explicit_release(
    sample_resource: Resource,
) -> None:
    store = InMemoryStore()
    engine = AvailabilityEngine(store)
    await engine.define_resource(sample_resource)
    slot_start = _T0 + timedelta(hours=1)
    slot_end = slot_start + timedelta(minutes=30)

    with time_machine.travel(_T0, tick=False):
        await engine.place_hold(
            sample_resource.id, slot_start, slot_end, ttl_seconds=60
        )

    # No release_hold()/confirm_hold() call happened on the first hold —
    # expiry must be lazy, discovered only on the next active-entries scan.
    with time_machine.travel(_T0 + timedelta(seconds=61), tick=False):
        second_hold = await engine.place_hold(
            sample_resource.id, slot_start, slot_end, ttl_seconds=60
        )

        assert second_hold is not None
