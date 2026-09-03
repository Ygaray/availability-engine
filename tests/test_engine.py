from datetime import UTC, datetime

import pytest

from availability_engine.contracts import Resource, SlotStatus
from availability_engine.engine import AvailabilityEngine
from availability_engine.errors import (
    CapacityExhaustedError,
    HoldNotFoundError,
    ResourceNotFoundError,
)
from availability_engine.storage.memory import InMemoryStore

# 2026-09-07 is a Monday. The window below (UTC) fully covers that Monday's
# calendar date in every timezone, so it always contains sample_resource's
# Monday 09:00-17:00 America/Chicago operating hours.
WINDOW_START = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)


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


async def test_place_hold_capacity_exhausted(sample_resource: Resource) -> None:
    # sample_resource.capacity == 1 — a second hold on the exact same slot
    # must be rejected, not silently accepted (T-01-05).
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.slots[0]

    await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )

    with pytest.raises(CapacityExhaustedError):
        await engine.place_hold(
            sample_resource.id, slot.start, slot.end, ttl_seconds=60
        )


async def test_place_hold_rejects_inverted_or_zero_length_slot(
    sample_resource: Resource,
) -> None:
    # WR-01: slot_end <= slot_start must be rejected at the boundary rather
    # than silently stored as a corrupt-duration Hold.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.slots[0]

    with pytest.raises(ValueError, match="must be after"):
        await engine.place_hold(
            sample_resource.id, slot.start, slot.start, ttl_seconds=60
        )

    with pytest.raises(ValueError, match="must be after"):
        await engine.place_hold(
            sample_resource.id, slot.end, slot.start, ttl_seconds=60
        )


async def test_confirm_hold_payload_roundtrip(sample_resource: Resource) -> None:
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    first_slot = result.slots[0]
    second_slot = next(s for s in result.slots if s.start != first_slot.start)

    sentinel_payload = {"secret_field": "sentinel-value-42"}

    hold = await engine.place_hold(
        sample_resource.id, first_slot.start, first_slot.end, ttl_seconds=60
    )
    booking = await engine.confirm_hold(hold.id, payload=sentinel_payload)
    assert booking.payload == sentinel_payload

    second_hold = await engine.place_hold(
        sample_resource.id, second_slot.start, second_slot.end, ttl_seconds=60
    )
    await engine.confirm_hold(second_hold.id, payload=sentinel_payload)

    # second_hold is already consumed by the confirm above — confirming it
    # again must raise, and the raised exception must never carry the
    # opaque payload's contents in its message (T-01-01).
    with pytest.raises(HoldNotFoundError) as exc_info:
        await engine.confirm_hold(second_hold.id, payload=sentinel_payload)

    assert "sentinel-value-42" not in str(exc_info.value)


async def test_unknown_resource_raises_consistently() -> None:
    # WR-02: get_availability and place_hold must fail the same way for an
    # unknown resource_id — a dedicated, catchable error, not a bare
    # ValueError on one path and a silent no-op on the other.
    engine = AvailabilityEngine(InMemoryStore())

    with pytest.raises(ResourceNotFoundError):
        await engine.get_availability("does-not-exist", WINDOW_START, WINDOW_END)

    with pytest.raises(ResourceNotFoundError):
        await engine.place_hold(
            "does-not-exist", WINDOW_START, WINDOW_END, ttl_seconds=60
        )


async def test_release_hold_frees_capacity(sample_resource: Resource) -> None:
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.slots[0]

    hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )
    await engine.release_hold(hold.id)

    # capacity-1 resource: the freed slot accepts a fresh hold immediately
    new_hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )
    assert new_hold.slot_start == slot.start

    # idempotent: releasing an already-released hold id does not raise
    await engine.release_hold(hold.id)
