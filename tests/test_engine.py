from datetime import UTC, datetime, time, timedelta

import pytest

from availability_engine.contracts import LocalInterval, ReasonCode, Resource, Weekday
from availability_engine.engine import AvailabilityEngine
from availability_engine.errors import (
    CapacityExhaustedError,
    HoldNotFoundError,
    OutsideHoursError,
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
    assert result.available
    assert not result.booked

    first_slot = result.available[0]
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
        s for s in result_after_confirm.booked if s.start == first_slot.start
    )
    assert confirmed_slot.remaining == 0

    second_slot = next(s for s in result.available if s.start != first_slot.start)
    second_hold = await engine.place_hold(
        sample_resource.id, second_slot.start, second_slot.end, ttl_seconds=60
    )
    await engine.release_hold(second_hold.id)

    result_after_release = await engine.get_availability(
        sample_resource.id, WINDOW_START, WINDOW_END
    )
    released_slot = next(
        s for s in result_after_release.available if s.start == second_slot.start
    )
    assert released_slot.remaining == released_slot.capacity


async def test_place_hold_capacity_exhausted(sample_resource: Resource) -> None:
    # sample_resource.capacity == 1 — a second hold on the exact same slot
    # must be rejected, not silently accepted (T-01-05).
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]

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
    slot = result.available[0]

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
    first_slot = result.available[0]
    second_slot = next(s for s in result.available if s.start != first_slot.start)

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


async def test_get_availability_rejects_naive_datetime(
    sample_resource: Resource,
) -> None:
    # GRID-04 / Success Criterion #5: get_availability's UtcDatetime
    # annotation has no runtime enforcement of its own on a plain async
    # method — it must actively guard the boundary (via time.require_utc)
    # rather than rely on an accidental downstream Pydantic construction.
    # This mirrors place_hold's naive-datetime rejection, but exercises the
    # get_availability facade call path directly (not just a Pydantic model
    # field in isolation).
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    naive_start = datetime(2026, 9, 7)
    naive_end = datetime(2026, 9, 8)

    with pytest.raises(ValueError, match="UTC-aware"):
        await engine.get_availability(sample_resource.id, naive_start, WINDOW_END)

    with pytest.raises(ValueError, match="UTC-aware"):
        await engine.get_availability(sample_resource.id, WINDOW_START, naive_end)


async def test_release_hold_frees_capacity(sample_resource: Resource) -> None:
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]

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


async def test_cancel_booking_frees_capacity(sample_resource: Resource) -> None:
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]

    hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )
    booking = await engine.confirm_hold(hold.id, payload={})
    assert await engine.cancel_booking(booking.id) is None

    result_after_cancel = await engine.get_availability(
        sample_resource.id, WINDOW_START, WINDOW_END
    )
    freed_slot = next(
        s for s in result_after_cancel.available if s.start == slot.start
    )
    assert freed_slot.remaining == freed_slot.capacity

    # capacity-1 resource: the freed slot accepts a fresh hold immediately
    new_hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )
    assert new_hold.slot_start == slot.start


async def test_place_hold_outside_hours(sample_resource: Resource) -> None:
    # HOLD-08: place_hold must reject a request entirely outside the
    # resource's declared operating hours (sample_resource only has hours
    # defined for Monday). 2026-09-08 is a Tuesday — outside any declared
    # LocalInterval for this resource.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    slot_start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    slot_end = slot_start + timedelta(minutes=30)

    with pytest.raises(OutsideHoursError) as exc_info:
        await engine.place_hold(
            sample_resource.id, slot_start, slot_end, ttl_seconds=60
        )

    assert exc_info.value.reason_code == ReasonCode.OUTSIDE_HOURS


async def test_place_hold_succeeds_after_midnight_on_overnight_hours_resource() -> (
    None
):
    # CR-01: a resource with an overnight (midnight-crossing) LocalInterval
    # (Monday 22:00->06:00) must accept a hold for a slot that falls
    # entirely after local midnight (e.g. Tuesday 05:30-06:00), because
    # get_availability already reports that identical slot as available.
    # Before the fix, place_hold called localize_operating_hours with the
    # query window narrowed to the exact requested slot, whose calendar
    # date is Tuesday — one day after the LocalInterval's MONDAY key — so
    # `hours` came back empty and OutsideHoursError was incorrectly raised.
    resource = Resource(
        id="night-shift",
        capacity=1,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(22, 0), end=time(6, 0))],
        },
        buffer=timedelta(minutes=0),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    # Window wide enough to include the overnight interval's after-midnight
    # tail (Tue 05:30-06:00 CDT == 2026-09-08 10:30-11:00 UTC).
    window_start = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 9, 9, 0, 0, tzinfo=UTC)

    result = await engine.get_availability(resource.id, window_start, window_end)
    slot = result.available[-1]  # 2026-09-08 10:30 UTC == Tue 05:30 CDT

    hold = await engine.place_hold(
        resource.id, slot.start, slot.end, ttl_seconds=60
    )
    assert hold.slot_start == slot.start
    assert hold.slot_end == slot.end


async def test_get_availability_survives_capacity_reduction_below_active_count() -> (
    None
):
    # CR-02: reducing a resource's capacity via define_resource while
    # holds/bookings already occupy the prior (higher) capacity must not
    # crash get_availability with an uncaught pydantic.ValidationError.
    # Before the fix, free_fragments computed `capacity - active_count`
    # unclamped, and a negative `remaining` violated PublicSlot.remaining's
    # `ge=0` constraint. It should instead degrade gracefully to
    # "fully booked" (remaining clamped to 0).
    resource = Resource(
        id="r1",
        capacity=3,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(17, 0))],
        },
        buffer=timedelta(minutes=0),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    result = await engine.get_availability(resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]

    for _ in range(3):
        await engine.place_hold(
            resource.id, slot.start, slot.end, ttl_seconds=600
        )  # fills capacity=3

    # Legal capacity edit — no upstream guard prevents this.
    await engine.define_resource(resource.model_copy(update={"capacity": 1}))

    result_after_reduction = await engine.get_availability(
        resource.id, WINDOW_START, WINDOW_END
    )
    reduced_slot = next(
        s for s in result_after_reduction.booked if s.start == slot.start
    )
    assert reduced_slot.remaining == 0
    assert reduced_slot.capacity == 1
