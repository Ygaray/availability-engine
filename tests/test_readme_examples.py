"""Automated regression guard for README.md's core code examples (PKG-02).

Upgrades 05-VALIDATION.md's "Manual-Only Verifications" doc-example row to
CI-enforced: both the async (`AvailabilityEngine`) and sync
(`SyncAvailabilityEngine`) facade examples shown in README.md's "Engine
facade" section are exercised here against the real, installed
`availability_engine` package -- never a mock -- with assertions on real
return values at every step, so a future README/API drift fails CI rather
than silently rotting the documented examples.
"""

from datetime import UTC, datetime

from availability_engine.contracts import BookingStatus, Resource
from availability_engine.engine import AvailabilityEngine
from availability_engine.storage.memory import InMemoryStore
from availability_engine.sync import SyncAvailabilityEngine

# 2026-09-07 is a Monday. The window below (UTC) fully covers that Monday's
# calendar date in every timezone, so it always contains sample_resource's
# Monday 09:00-17:00 America/Chicago operating hours (matches
# tests/test_engine.py's convention).
WINDOW_START = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)


async def test_readme_async_example_end_to_end(sample_resource: Resource) -> None:
    """README's async `AvailabilityEngine` example: define_resource ->
    get_availability -> place_hold -> confirm_hold -> cancel_booking, each
    step asserted against a real, non-None return value -- a regression
    that silently returns empty/wrong data must fail this test."""
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(
        sample_resource.id, WINDOW_START, WINDOW_END
    )
    assert result.available

    slot = result.available[0]
    hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )
    assert hold.id
    assert hold.slot_start == slot.start
    assert hold.slot_end == slot.end

    booking = await engine.confirm_hold(hold.id, payload={"order_id": "abc-123"})
    assert booking.id
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.payload == {"order_id": "abc-123"}

    await engine.cancel_booking(booking.id)


def test_readme_sync_example_end_to_end(sample_resource: Resource) -> None:
    """README's sync `SyncAvailabilityEngine` example, run from a plain
    (non-async) test function: the same call sequence as the async test
    above, exercised through the background-thread bridge, ending in
    close()."""
    engine = SyncAvailabilityEngine(InMemoryStore())
    try:
        engine.define_resource(sample_resource)

        result = engine.get_availability(
            sample_resource.id, WINDOW_START, WINDOW_END
        )
        assert result.available

        slot = result.available[0]
        hold = engine.place_hold(
            sample_resource.id, slot.start, slot.end, ttl_seconds=60
        )
        assert hold.id
        assert hold.slot_start == slot.start
        assert hold.slot_end == slot.end

        booking = engine.confirm_hold(hold.id, payload={"order_id": "abc-123"})
        assert booking.id
        assert booking.status == BookingStatus.CONFIRMED
        assert booking.payload == {"order_id": "abc-123"}

        engine.cancel_booking(booking.id)
    finally:
        engine.close()
