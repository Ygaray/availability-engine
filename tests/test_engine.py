import asyncio
import inspect
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from availability_engine.contracts import (
    BlockInterval,
    LocalInterval,
    ReasonCode,
    Resource,
    SlotStatus,
    Weekday,
)
from availability_engine.engine import AvailabilityEngine
from availability_engine.errors import (
    BookingNotFoundError,
    CapacityExhaustedError,
    HoldNotFoundError,
    IdempotencyConflictError,
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


async def test_cancel_booking_not_found_or_already_cancelled(
    sample_resource: Resource,
) -> None:
    # D-04: an unknown booking_id, and a booking_id already cancelled, both
    # raise BookingNotFoundError — never a silent no-op, unlike release_hold.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    with pytest.raises(BookingNotFoundError) as unknown_exc_info:
        await engine.cancel_booking("does-not-exist")
    assert unknown_exc_info.value.reason_code == ReasonCode.NOT_FOUND

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]
    hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )
    booking = await engine.confirm_hold(hold.id, payload={})
    await engine.cancel_booking(booking.id)

    with pytest.raises(BookingNotFoundError) as already_cancelled_exc_info:
        await engine.cancel_booking(booking.id)
    assert already_cancelled_exc_info.value.reason_code == ReasonCode.NOT_FOUND


async def test_cancel_booking_on_hold_id_raises_not_found(
    sample_resource: Resource,
) -> None:
    # HOLD-06 edge probe: cancel_booking looks up only _bookings, so an
    # active Hold's id (never confirmed into a Booking) must never be
    # accepted — the Hold/Booking id namespaces are never conflated.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]
    hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )

    with pytest.raises(BookingNotFoundError):
        await engine.cancel_booking(hold.id)


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


async def test_place_hold_idempotent_replay(sample_resource: Resource) -> None:
    # HOLD-07: a same-key/same-args replay of place_hold on a capacity-1
    # resource returns the identical Hold and never raises
    # CapacityExhaustedError on the second call.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]

    first = await engine.place_hold(
        sample_resource.id,
        slot.start,
        slot.end,
        ttl_seconds=60,
        idempotency_key="k1",
    )
    second = await engine.place_hold(
        sample_resource.id,
        slot.start,
        slot.end,
        ttl_seconds=60,
        idempotency_key="k1",
    )

    assert first.id == second.id


async def test_place_hold_idempotency_conflict(sample_resource: Resource) -> None:
    # HOLD-07: same idempotency_key with a materially different slot_start
    # raises IdempotencyConflictError rather than silently returning either
    # a stale result or double-acting.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    first_slot = result.available[0]
    second_slot = next(s for s in result.available if s.start != first_slot.start)

    await engine.place_hold(
        sample_resource.id,
        first_slot.start,
        first_slot.end,
        ttl_seconds=60,
        idempotency_key="k2",
    )

    with pytest.raises(IdempotencyConflictError) as exc_info:
        await engine.place_hold(
            sample_resource.id,
            second_slot.start,
            second_slot.end,
            ttl_seconds=60,
            idempotency_key="k2",
        )

    assert exc_info.value.reason_code == ReasonCode.IDEMPOTENCY_CONFLICT


async def test_place_hold_concurrent_same_key_race_returns_same_hold(
    sample_resource: Resource,
) -> None:
    # HOLD-07: two concurrent place_hold calls sharing the same
    # idempotency_key and identical args, issued via asyncio.gather, are
    # serialized by InMemoryStore's single asyncio.Lock — both resolve to
    # the same Hold.id and capacity is never double-consumed.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]

    first, second = await asyncio.gather(
        engine.place_hold(
            sample_resource.id,
            slot.start,
            slot.end,
            ttl_seconds=60,
            idempotency_key="race-key",
        ),
        engine.place_hold(
            sample_resource.id,
            slot.start,
            slot.end,
            ttl_seconds=60,
            idempotency_key="race-key",
        ),
    )

    assert first.id == second.id

    result_after = await engine.get_availability(
        sample_resource.id, WINDOW_START, WINDOW_END
    )
    booked_slot = next(s for s in result_after.booked if s.start == slot.start)
    assert booked_slot.remaining == 0


async def test_confirm_hold_idempotent_replay(sample_resource: Resource) -> None:
    # HOLD-07: a same-key/same-(hold_id, payload) replay of confirm_hold
    # returns the identical Booking without raising HoldNotFoundError, even
    # though the underlying hold was already consumed and deleted by the
    # first call's success.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]
    hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )

    payload = {"order_id": "replay-1"}
    first = await engine.confirm_hold(hold.id, payload=payload, idempotency_key="c1")
    second = await engine.confirm_hold(hold.id, payload=payload, idempotency_key="c1")

    assert first.id == second.id


async def test_idempotency_key_scoped_per_operation_type(
    sample_resource: Resource,
) -> None:
    # D-01: the same literal idempotency key string used for an unrelated
    # place_hold call and confirm_hold call never collides — each operation's
    # idempotency record is scoped by (operation_type, key).
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    first_slot = result.available[0]
    second_slot = next(s for s in result.available if s.start != first_slot.start)

    # Consume first_slot's hold via confirm_hold under the shared key.
    hold_for_confirm = await engine.place_hold(
        sample_resource.id, first_slot.start, first_slot.end, ttl_seconds=60
    )
    booking = await engine.confirm_hold(
        hold_for_confirm.id, payload={"x": 1}, idempotency_key="shared-key"
    )
    assert booking.resource_id == sample_resource.id

    # An unrelated place_hold on a different slot, using the exact same key
    # string, must not collide with the confirm_hold record above and must
    # return its own correctly-typed Hold.
    hold = await engine.place_hold(
        sample_resource.id,
        second_slot.start,
        second_slot.end,
        ttl_seconds=60,
        idempotency_key="shared-key",
    )
    assert hold.slot_start == second_slot.start


async def test_confirm_hold_idempotency_conflict(sample_resource: Resource) -> None:
    # WR-01: mirrors test_place_hold_idempotency_conflict for confirm_hold —
    # same idempotency_key with a materially different payload raises
    # IdempotencyConflictError rather than silently returning either a stale
    # result or double-acting.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]
    hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )

    await engine.confirm_hold(
        hold.id, payload={"order_id": "a"}, idempotency_key="conflict-c"
    )

    with pytest.raises(IdempotencyConflictError) as exc_info:
        await engine.confirm_hold(
            hold.id, payload={"order_id": "b"}, idempotency_key="conflict-c"
        )

    assert exc_info.value.reason_code == ReasonCode.IDEMPOTENCY_CONFLICT


async def test_confirm_hold_idempotency_payload_must_be_json_serializable(
    sample_resource: Resource,
) -> None:
    # WR-02: a non-JSON-serializable payload used with an idempotency_key
    # must raise a clear TypeError up front rather than silently producing
    # a fingerprint via `default=str` that may not be reproducible across
    # calls with a logically identical payload.
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(sample_resource)

    result = await engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
    slot = result.available[0]
    hold = await engine.place_hold(
        sample_resource.id, slot.start, slot.end, ttl_seconds=60
    )

    with pytest.raises(TypeError):
        await engine.confirm_hold(
            hold.id, payload={"tags": {"a", "b"}}, idempotency_key="non-json-k"
        )


# 26-10-PLAN.md Task 1: get_availability — duration-aware, block-excluding,
# buffer-aware-listing, business_id-scoped.


async def test_get_availability_duration_aware_slots_stepped_by_slot_duration() -> (
    None
):
    # Test 2: duration is genuinely query-time, not resource-fixed —
    # slot_duration=30min, queried with duration=60min, returns 60-minute
    # candidates stepped by the resource's own 30-minute slot_duration.
    resource = Resource(
        id="duration-resource",
        capacity=1,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(17, 0))],
        },
        buffer=timedelta(0),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    result = await engine.get_availability(
        resource.id, WINDOW_START, WINDOW_END, duration=timedelta(minutes=60)
    )

    assert result.available
    assert not result.booked
    for slot in result.available:
        assert slot.end - slot.start == timedelta(minutes=60)
    starts = sorted(s.start for s in result.available)
    assert starts[1] - starts[0] == timedelta(minutes=30)


async def test_get_availability_business_id_scoping_raises_resource_not_found(
    sample_resource: Resource,
) -> None:
    # Test 4: two tenants' resources sharing the same resource_id string are
    # genuinely separate namespaces, not merely filtered post-hoc.
    engine = AvailabilityEngine(InMemoryStore())
    resource_biz_b = sample_resource.model_copy(update={"business_id": "biz-b"})
    await engine.define_resource(resource_biz_b)

    with pytest.raises(ResourceNotFoundError):
        await engine.get_availability(
            sample_resource.id, WINDOW_START, WINDOW_END, business_id="biz-a"
        )

    # Sanity: the resource IS reachable under its real business_id.
    result = await engine.get_availability(
        sample_resource.id, WINDOW_START, WINDOW_END, business_id="biz-b"
    )
    assert result.available


async def test_get_availability_duration_listing_is_buffer_aware_both_ways() -> (
    None
):
    # Test 5 (closes review's HIGH "opening listings still ignore buffers
    # around existing entries"): neither the candidate immediately BEFORE an
    # existing hold, nor the candidate immediately AFTER it, is offered as
    # AVAILABLE — even though neither raw-overlaps the hold at all (they
    # only touch its edges) — because both fall within the resource's
    # 15-minute buffer. Uses the SAME symmetric padded-overlap
    # peak_concurrency predicate place_hold/store.py uses.
    resource = Resource(
        id="buffer-resource",
        capacity=1,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(8, 30), end=time(10, 0))],
        },
        buffer=timedelta(minutes=15),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    # Construct the held slot (09:00-09:30 local) and its neighbors
    # directly — the duration-aware grid's anchor (step = slot_duration
    # alone) differs from the v1/duration=None grid's anchor (step =
    # slot_duration + buffer), so a v1 probe cannot be used to locate these
    # three 30-minute-apart candidates.
    tz = ZoneInfo("America/Chicago")
    before_start = datetime(2026, 9, 7, 8, 30, tzinfo=tz).astimezone(UTC)
    held_start = datetime(2026, 9, 7, 9, 0, tzinfo=tz).astimezone(UTC)
    held_end = datetime(2026, 9, 7, 9, 30, tzinfo=tz).astimezone(UTC)
    after_start = datetime(2026, 9, 7, 9, 30, tzinfo=tz).astimezone(UTC)

    await engine.place_hold(resource.id, held_start, held_end, ttl_seconds=600)

    result = await engine.get_availability(
        resource.id, WINDOW_START, WINDOW_END, duration=timedelta(minutes=30)
    )
    by_start = {s.start: s for s in result.available + result.booked}

    assert by_start[before_start].status == SlotStatus.BOOKED
    assert by_start[before_start].remaining == 0
    assert by_start[after_start].status == SlotStatus.BOOKED
    assert by_start[after_start].remaining == 0


async def test_duration_aware_grid_anchors_independent_of_window_and_blocks() -> (
    None
):
    # Test 6 (Cycle-2, closes review's two HIGH findings): the duration-aware
    # grid is anchored to the resource's OWN operating-interval start,
    # independent of where an off-grid query window begins, or where a
    # non-grid-aligned block boundary falls.
    resource = Resource(
        id="anchor-resource",
        capacity=1,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(17, 0))],
        },
        buffer=timedelta(0),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
        blocks=[
            # 11:00-11:10 local -- ends at a NON-grid-aligned instant
            # relative to the 09:00-anchored 30-minute grid.
            BlockInterval(
                start=datetime(2026, 9, 7, 11, 0),
                end=datetime(2026, 9, 7, 11, 10),
            )
        ],
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    probe = await engine.get_availability(resource.id, WINDOW_START, WINDOW_END)
    day_start = probe.available[0].start  # the resource's own 09:00 anchor, UTC

    # Off-grid window start: 15 minutes after the resource's own anchor.
    window_start = day_start + timedelta(minutes=15)

    result = await engine.get_availability(
        resource.id, window_start, WINDOW_END, duration=timedelta(minutes=30)
    )
    all_slots = sorted(result.available + result.booked, key=lambda s: s.start)

    # (a) window CONTAINMENT, never mere overlap: the FIRST returned
    # candidate is the next ALIGNED grid point (day_start + 30min), never
    # day_start + 15min (which would straddle the window's edge and could
    # never actually be held in full).
    assert all_slots[0].start == day_start + timedelta(minutes=30)

    # (b) block exclusion never re-anchors the grid: candidates resume at
    # the next ALIGNED grid point after the block (day_start + 2h30m ==
    # 11:30 local), never at the block's own (off-grid) end (11:10 local).
    starts = {s.start for s in all_slots}
    off_grid_block_end = day_start + timedelta(hours=2, minutes=10)  # 11:10
    aligned_resume_point = day_start + timedelta(hours=2, minutes=30)  # 11:30
    assert off_grid_block_end not in starts
    assert aligned_resume_point in starts


# 26-10-PLAN.md Task 2: place_hold — blocked-time rejection, business_id
# scoping (confirm_hold/cancel_booking stay UNCHANGED — D-A).


async def test_place_hold_accepts_slot_whose_buffer_extends_past_closing() -> None:
    # Test 2 (Pitfall 3 regression, explicit): place_hold's operating-hours
    # check must only ever see the UNPADDED requested interval — buffer
    # padding applies exclusively to the storage-layer capacity check
    # against OTHER entries (store.py/memory.py, Plan 26-09), never to the
    # resource's own closing-time boundary. A 45-minute buffer would push
    # 09:30-10:00's padded end to 10:45, past the resource's 10:00 close —
    # this must still be ACCEPTED when no other booking conflicts.
    resource = Resource(
        id="closing-time-resource",
        capacity=1,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(10, 0))],
        },
        buffer=timedelta(minutes=45),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    tz = ZoneInfo("America/Chicago")
    slot_start = datetime(2026, 9, 7, 9, 30, tzinfo=tz).astimezone(UTC)
    slot_end = datetime(2026, 9, 7, 10, 0, tzinfo=tz).astimezone(UTC)

    hold = await engine.place_hold(
        resource.id, slot_start, slot_end, ttl_seconds=60
    )
    assert hold.slot_start == slot_start
    assert hold.slot_end == slot_end


async def test_place_hold_rejects_request_inside_blocked_range() -> None:
    # Test 3: a place_hold request landing inside a BlockInterval raises
    # OutsideHoursError, reusing the existing, closed ReasonCode.OUTSIDE_HOURS
    # value — D-07 explicitly rejects widening ReasonCode.
    resource = Resource(
        id="blocked-hold-resource",
        capacity=1,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(17, 0))],
        },
        buffer=timedelta(0),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
        blocks=[
            BlockInterval(
                start=datetime(2026, 9, 7, 12, 0),
                end=datetime(2026, 9, 7, 14, 0),
            )
        ],
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    tz = ZoneInfo("America/Chicago")
    slot_start = datetime(2026, 9, 7, 12, 30, tzinfo=tz).astimezone(UTC)
    slot_end = slot_start + timedelta(minutes=30)

    with pytest.raises(OutsideHoursError) as exc_info:
        await engine.place_hold(resource.id, slot_start, slot_end, ttl_seconds=60)

    assert exc_info.value.reason_code == ReasonCode.OUTSIDE_HOURS


async def test_place_hold_business_id_scoping_raises_resource_not_found(
    sample_resource: Resource,
) -> None:
    # Test 4: namespace isolation at hold time, matching get_availability's
    # Test 4.
    engine = AvailabilityEngine(InMemoryStore())
    resource_biz_b = sample_resource.model_copy(update={"business_id": "biz-b"})
    await engine.define_resource(resource_biz_b)

    result = await engine.get_availability(
        sample_resource.id, WINDOW_START, WINDOW_END, business_id="biz-b"
    )
    slot = result.available[0]

    with pytest.raises(ResourceNotFoundError):
        await engine.place_hold(
            sample_resource.id,
            slot.start,
            slot.end,
            ttl_seconds=60,
            business_id="biz-a",
        )


def test_confirm_hold_and_cancel_booking_signatures_have_no_business_id_param() -> (
    None
):
    # Test 5 (closes review's HIGH "confirm/cancel remain incompatible with
    # the consumer adapter", a NEGATIVE assertion): confirm_hold and
    # cancel_booking never gain a business_id parameter anywhere in this
    # plan — engine_adapter.py (Plan 26-05) and the storage protocol (Plan
    # 26-09) both call these with none.
    confirm_params = inspect.signature(AvailabilityEngine.confirm_hold).parameters
    cancel_params = inspect.signature(AvailabilityEngine.cancel_booking).parameters
    assert "business_id" not in confirm_params
    assert "business_id" not in cancel_params
