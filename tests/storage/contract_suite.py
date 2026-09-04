"""Shared, parametrized storage-backend contract suite (STORE-02).

Currently parametrized over [InMemoryStore] only (Phase 1). Phase 4 adds
SQLStore to the single `parametrize` list below without rewriting any test
body in this file — that's the whole point of this file's existence.
"""

from datetime import UTC, datetime, timedelta

import pytest
import time_machine

from availability_engine.contracts import Resource
from availability_engine.core.intervals import Interval
from availability_engine.errors import CapacityExhaustedError
from availability_engine.storage.memory import InMemoryStore


@pytest.mark.parametrize("backend_factory", [InMemoryStore], ids=["in-memory"])
class TestStorageContractSuite:
    """Behavior every StorageBackend implementation must satisfy."""

    async def test_save_and_get_resource_roundtrip(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        backend = backend_factory()
        await backend.save_resource(sample_resource)

        retrieved = await backend.get_resource(sample_resource.id)

        assert retrieved == sample_resource

    async def test_get_resource_unknown_returns_none(
        self, backend_factory: type[InMemoryStore]
    ) -> None:
        backend = backend_factory()

        assert await backend.get_resource("does-not-exist") is None

    async def test_placed_hold_appears_in_active_entries(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        hold = await backend.place_hold(
            sample_resource.id, slot, capacity=sample_resource.capacity, ttl_seconds=60
        )
        entries = await backend.get_active_entries(sample_resource.id, slot)

        assert hold in entries

    async def test_place_hold_uses_authoritative_stored_capacity(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # WR-03: the backend must enforce capacity from its own resource
        # record, not blindly trust a caller-supplied `capacity` snapshot
        # that may be stale (e.g. a concurrent `define_resource` changed
        # it). sample_resource.capacity == 1; a caller passing a wildly
        # wrong capacity=100 must still be rejected on the second hold.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        await backend.place_hold(
            sample_resource.id, slot, capacity=100, ttl_seconds=60
        )

        with pytest.raises(CapacityExhaustedError):
            await backend.place_hold(
                sample_resource.id, slot, capacity=100, ttl_seconds=60
            )

    async def test_get_active_entries_excludes_expired_hold(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # AVAIL-03: the shared active-entries primitive itself must exclude
        # an expired hold, independent of place_hold's capacity check (which
        # test_expired_hold_stops_blocking_capacity_with_no_explicit_release
        # in tests/test_hold_expiry.py already covers end-to-end).
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        t0 = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)
        slot = Interval(start=t0, end=t0 + timedelta(minutes=30))

        with time_machine.travel(t0, tick=False):
            hold = await backend.place_hold(
                sample_resource.id,
                slot,
                capacity=sample_resource.capacity,
                ttl_seconds=60,
            )

        with time_machine.travel(t0 + timedelta(seconds=61), tick=False):
            entries = await backend.get_active_entries(sample_resource.id, slot)

            assert hold not in entries

    async def test_get_active_entries_empty_when_no_entries(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # AVAIL-03: a resource with zero active holds/bookings must return
        # an empty list from get_active_entries for any window.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        entries = await backend.get_active_entries(sample_resource.id, slot)

        assert entries == []
