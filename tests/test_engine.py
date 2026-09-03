from datetime import datetime, timezone

from availability_engine.contracts import Resource, SlotStatus
from availability_engine.engine import AvailabilityEngine
from availability_engine.storage.memory import InMemoryStore

# 2026-09-07 is a Monday. The window below (UTC) fully covers that Monday's
# calendar date in every timezone, so it always contains sample_resource's
# Monday 09:00-17:00 America/Chicago operating hours.
WINDOW_START = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)


async def test_canary() -> None:
    assert True


async def test_get_availability_end_to_end(sample_resource: Resource) -> None:
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    assert result.slots
    assert all(slot.status == SlotStatus.AVAILABLE for slot in result.slots)

    first_slot = result.slots[0]
    hold = await engine.place_hold(
        sample_resource.id, first_slot.start, first_slot.end, ttl_seconds=60
    )
    assert hold.slot_start == first_slot.start
    assert hold.slot_end == first_slot.end

    payload = {"order_id": "abc-123"}
    booking = await engine.confirm_hold(hold.id, payload=payload)
    assert booking.payload == payload

    result_after_confirm = await engine.get_availability(
        sample_resource.id, WINDOW_START, WINDOW_END
    )
    confirmed_slot = next(
        s for s in result_after_confirm.slots if s.start == first_slot.start
    )
    assert confirmed_slot.status == SlotStatus.BOOKED

    second_slot = next(s for s in result.slots if s.start != first_slot.start)
    second_hold = await engine.place_hold(
        sample_resource.id, second_slot.start, second_slot.end, ttl_seconds=60
    )
    await engine.release_hold(second_hold.id)

    result_after_release = await engine.get_availability(
        sample_resource.id, WINDOW_START, WINDOW_END
    )
    released_slot = next(
        s for s in result_after_release.slots if s.start == second_slot.start
    )
    assert released_slot.status == SlotStatus.AVAILABLE
