"""26-09-PLAN.md Task 2 (D-05): `place_hold`'s capacity check uses
`peak_concurrency` against symmetrically buffer-padded busy intervals,
fetched over a buffer-widened window — proven IDENTICALLY across
InMemoryStore and SQLStore (not a weaker in-memory approximation), per
`storage/memory.py`'s own module docstring.

Reuses `tests/storage/conftest.py`'s `backend_factory` indirect-parametrize
fixture (the same mechanism `contract_suite.py` uses) so every test here
runs against in-memory, sqlite, AND postgres without duplicating setup.
"""

from datetime import UTC, datetime, time, timedelta

import pytest

from availability_engine.contracts import (
    DEFAULT_BUSINESS_ID,
    LocalInterval,
    Resource,
    Weekday,
)
from availability_engine.core.intervals import Interval
from availability_engine.errors import CapacityExhaustedError
from availability_engine.storage.memory import InMemoryStore


def _make_resource(capacity: int, buffer: timedelta) -> Resource:
    return Resource(
        id="buffer-capacity-resource",
        capacity=capacity,
        # Full-day hours — storage-level place_hold never checks operating
        # hours (that's engine.py's job, Test 5/Pitfall 3 below); this is
        # just a validly-shaped Resource.
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(0, 0), end=time(23, 59))],
        },
        buffer=buffer,
        timezone="UTC",
        slot_duration=timedelta(minutes=30),
    )


@pytest.mark.parametrize(
    "backend_factory", ["in-memory", "sqlite", "postgres"], indirect=True
)
class TestPlaceHoldBufferCapacity:
    pytestmark = pytest.mark.asyncio(loop_scope="session")

    async def test_peak_concurrency_correctly_rejects_third_overlapping_hold_at_units_2(
        self, backend_factory: type[InMemoryStore]
    ) -> None:
        # Test 1: units=2/buffer=0 with TWO existing, overlapping-but-not-
        # identical-start-time holds correctly rejects a THIRD hold that
        # would overlap both (peak_concurrency correctly computes 2
        # simultaneously active, not an undercount from a naive
        # non-overlapping-start assumption).
        backend = backend_factory()
        resource = _make_resource(capacity=2, buffer=timedelta(0))
        await backend.save_resource(resource)

        first = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )
        second = Interval(
            start=datetime(2026, 9, 7, 15, 15, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 45, tzinfo=UTC),
        )
        third = Interval(
            start=datetime(2026, 9, 7, 15, 20, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 25, tzinfo=UTC),
        )

        await backend.place_hold(
            DEFAULT_BUSINESS_ID,
            resource.id,
            first,
            capacity=resource.capacity,
            ttl_seconds=60,
        )
        await backend.place_hold(
            DEFAULT_BUSINESS_ID,
            resource.id,
            second,
            capacity=resource.capacity,
            ttl_seconds=60,
        )

        with pytest.raises(CapacityExhaustedError):
            await backend.place_hold(
                DEFAULT_BUSINESS_ID,
                resource.id,
                third,
                capacity=resource.capacity,
                ttl_seconds=60,
            )

    async def test_buffer_rejects_hold_starting_within_buffer_of_prior_entrys_end(
        self, backend_factory: type[InMemoryStore]
    ) -> None:
        # Test 2 (existing-entry's trailing edge reaching forward): buffer=
        # 15min, one existing hold rejects a new hold starting 10 minutes
        # after it ends (padded-busy-interval overlap), but ACCEPTS one
        # starting 20 minutes after (outside the padded buffer).
        backend = backend_factory()
        resource = _make_resource(capacity=1, buffer=timedelta(minutes=15))
        await backend.save_resource(resource)

        existing = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )
        await backend.place_hold(
            DEFAULT_BUSINESS_ID,
            resource.id,
            existing,
            capacity=resource.capacity,
            ttl_seconds=60,
        )

        too_close = Interval(
            start=datetime(2026, 9, 7, 15, 40, tzinfo=UTC),
            end=datetime(2026, 9, 7, 16, 10, tzinfo=UTC),
        )
        with pytest.raises(CapacityExhaustedError):
            await backend.place_hold(
                DEFAULT_BUSINESS_ID,
                resource.id,
                too_close,
                capacity=resource.capacity,
                ttl_seconds=60,
            )

        far_enough = Interval(
            start=datetime(2026, 9, 7, 15, 50, tzinfo=UTC),
            end=datetime(2026, 9, 7, 16, 20, tzinfo=UTC),
        )
        accepted = await backend.place_hold(
            DEFAULT_BUSINESS_ID,
            resource.id,
            far_enough,
            capacity=resource.capacity,
            ttl_seconds=60,
        )
        assert accepted.slot_start == far_enough.start

    async def test_buffer_rejects_hold_whose_own_trailing_buffer_reaches_a_later_entry(
        self, backend_factory: type[InMemoryStore]
    ) -> None:
        # Test 3 (the REQUESTED interval's own trailing edge reaching
        # forward into a LATER entry — closes review's HIGH "padding only
        # existing entries misses the opposite direction"): buffer=15min,
        # one existing booking at [11:00, 12:00) rejects a new hold request
        # for [10:00, 10:50) (the REQUEST's own trailing buffer, if granted,
        # would extend busy to 10:50+15=11:05, overlapping the existing
        # entry's start at 11:00), but ACCEPTS a request for [10:00, 10:44)
        # (10:44+15=10:59 < 11:00).
        backend = backend_factory()
        resource = _make_resource(capacity=1, buffer=timedelta(minutes=15))
        await backend.save_resource(resource)

        later_entry = Interval(
            start=datetime(2026, 9, 7, 11, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        )
        await backend.place_hold(
            DEFAULT_BUSINESS_ID,
            resource.id,
            later_entry,
            capacity=resource.capacity,
            ttl_seconds=60,
        )

        too_close_request = Interval(
            start=datetime(2026, 9, 7, 10, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 10, 50, tzinfo=UTC),
        )
        with pytest.raises(CapacityExhaustedError):
            await backend.place_hold(
                DEFAULT_BUSINESS_ID,
                resource.id,
                too_close_request,
                capacity=resource.capacity,
                ttl_seconds=60,
            )

        far_enough_request = Interval(
            start=datetime(2026, 9, 7, 10, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 10, 44, tzinfo=UTC),
        )
        accepted = await backend.place_hold(
            DEFAULT_BUSINESS_ID,
            resource.id,
            far_enough_request,
            capacity=resource.capacity,
            ttl_seconds=60,
        )
        assert accepted.slot_start == far_enough_request.start

    async def test_buffer_check_retrieves_entries_outside_the_unwidened_slot_window(
        self, backend_factory: type[InMemoryStore]
    ) -> None:
        # Test 4 (the buffer check can actually SEE the conflicting entry —
        # closes review's HIGH "the buffer check cannot retrieve the
        # entries it needs"): reproduces the Test 2 scenario and proves, via
        # a black-box check on the public get_active_entries primitive
        # itself, that the UNWIDENED slot would never have retrieved the
        # conflicting entry at all — yet place_hold still correctly rejects
        # the request, proving its OWN internal fetch window is buffer-
        # widened rather than reusing the raw requested slot.
        backend = backend_factory()
        resource = _make_resource(capacity=1, buffer=timedelta(minutes=15))
        await backend.save_resource(resource)

        existing = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )
        await backend.place_hold(
            DEFAULT_BUSINESS_ID,
            resource.id,
            existing,
            capacity=resource.capacity,
            ttl_seconds=60,
        )

        new_slot = Interval(
            start=datetime(2026, 9, 7, 15, 40, tzinfo=UTC),
            end=datetime(2026, 9, 7, 16, 10, tzinfo=UTC),
        )

        # The UNWIDENED fetch (the public primitive, called directly over
        # the raw requested slot) finds nothing — `existing` does not
        # overlap `new_slot` at all.
        unwidened = await backend.get_active_entries(
            DEFAULT_BUSINESS_ID, resource.id, new_slot
        )
        assert unwidened == []

        # Yet place_hold must still reject — proving its internal fetch
        # window is widened by `buffer` on both sides, not the raw slot.
        with pytest.raises(CapacityExhaustedError):
            await backend.place_hold(
                DEFAULT_BUSINESS_ID,
                resource.id,
                new_slot,
                capacity=resource.capacity,
                ttl_seconds=60,
            )

    async def test_place_hold_trusts_caller_capacity_for_unregistered_resource_with_buffer_logic(  # noqa: E501
        self, backend_factory: type[InMemoryStore]
    ) -> None:
        # Cycle-2 guard regression: an unregistered resource (no
        # save_resource call) must resolve buffer=timedelta(0) via the
        # `resource is not None` guard rather than raising AttributeError
        # on a bare `resource.buffer` access — mirrors
        # contract_suite.py's own
        # test_place_hold_trusts_caller_capacity_for_unregistered_resource,
        # re-asserted here specifically against the NEW buffer-padding code
        # path this task adds.
        backend = backend_factory()
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        hold = await backend.place_hold(
            DEFAULT_BUSINESS_ID, "never-registered", slot, capacity=1, ttl_seconds=60
        )
        assert hold.resource_id == "never-registered"
