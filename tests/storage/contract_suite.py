"""Shared, parametrized storage-backend contract suite (STORE-02).

Currently parametrized over [InMemoryStore] only (Phase 1). Phase 4 adds
SQLStore to the single `parametrize` list below without rewriting any test
body in this file — that's the whole point of this file's existence.
"""

from datetime import UTC, datetime, timedelta

import pytest
import time_machine

from availability_engine.contracts import BookingStatus, Resource
from availability_engine.core.intervals import Interval
from availability_engine.errors import (
    BookingNotFoundError,
    CapacityExhaustedError,
    HoldNotFoundError,
    IdempotencyConflictError,
)
from availability_engine.storage.memory import InMemoryStore


@pytest.mark.parametrize(
    "backend_factory", ["in-memory", "sqlite", "postgres"], indirect=True
)
class TestStorageContractSuite:
    """Behavior every StorageBackend implementation must satisfy."""

    # 04-02-PLAN.md Task 1: pg_engine/sqlite_engine are session-scoped async
    # fixtures (loop_scope="session"), but each test function otherwise gets
    # its own event loop by default (asyncio_default_fixture_loop_scope is
    # unset, defaulting to "function"). asyncpg's connections are bound to
    # the event loop that created them and raise "attached to a different
    # loop" if a later test's own loop differs from the session-scoped
    # engine's loop — so every test in this class must also run on the
    # session-scoped loop. aiosqlite tolerates cross-loop reuse (it re-reads
    # the current running loop on every call rather than binding once), so
    # this was never a visible problem before Postgres was added.
    pytestmark = pytest.mark.asyncio(loop_scope="session")

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

    async def test_cancel_booking_frees_capacity_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # HOLD-06 at the storage-protocol level (STORE-04): proves Phase 4's
        # future SQL backend is exercised against identical behavior without
        # rewriting this suite.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        hold = await backend.place_hold(
            sample_resource.id, slot, capacity=sample_resource.capacity, ttl_seconds=60
        )
        booking = await backend.confirm_hold(hold.id, payload={})
        await backend.cancel_booking(booking.id)

        entries = await backend.get_active_entries(sample_resource.id, slot)

        assert booking not in entries

    async def test_cancel_booking_unknown_or_already_cancelled_raises(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # D-04 at the storage-protocol level: an unknown or already-cancelled
        # booking_id must be rejected, never a silent no-op.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        with pytest.raises(BookingNotFoundError):
            await backend.cancel_booking("does-not-exist")

        hold = await backend.place_hold(
            sample_resource.id, slot, capacity=sample_resource.capacity, ttl_seconds=60
        )
        booking = await backend.confirm_hold(hold.id, payload={})
        await backend.cancel_booking(booking.id)

        with pytest.raises(BookingNotFoundError):
            await backend.cancel_booking(booking.id)

    async def test_place_hold_idempotent_replay_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # HOLD-07/STORE-04: exercises idempotent place_hold directly against
        # the storage backend (not the engine facade), so Phase 4's SQL
        # backend addition is proven against identical behavior without
        # rewriting this test body.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        first = await backend.place_hold(
            sample_resource.id,
            slot,
            capacity=sample_resource.capacity,
            ttl_seconds=60,
            idempotency_key="storage-k",
        )
        second = await backend.place_hold(
            sample_resource.id,
            slot,
            capacity=sample_resource.capacity,
            ttl_seconds=60,
            idempotency_key="storage-k",
        )

        assert first.id == second.id

    async def test_place_hold_idempotent_replay_after_release_creates_fresh_hold_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # CR-01: once the original Hold behind a cached idempotency record
        # has been explicitly released, a replay must NOT return the stale
        # (now-nonexistent) Hold — capacity is free again, so it must fall
        # through and create a genuinely fresh Hold instead of permanently
        # stranding this idempotency key.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        first = await backend.place_hold(
            sample_resource.id,
            slot,
            capacity=sample_resource.capacity,
            ttl_seconds=60,
            idempotency_key="release-k",
        )
        await backend.release_hold(first.id)

        second = await backend.place_hold(
            sample_resource.id,
            slot,
            capacity=sample_resource.capacity,
            ttl_seconds=60,
            idempotency_key="release-k",
        )

        assert second.id != first.id
        entries = await backend.get_active_entries(sample_resource.id, slot)
        assert second in entries

    async def test_place_hold_idempotent_replay_after_expiry_creates_fresh_hold_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # CR-01: an expired (but never explicitly released) Hold must also
        # be treated as stale on replay — it no longer counts as active
        # (AVAIL-03), so the replay must fall through and create a fresh
        # Hold rather than returning the expired snapshot.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        t0 = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)
        slot = Interval(start=t0, end=t0 + timedelta(minutes=30))

        with time_machine.travel(t0, tick=False):
            first = await backend.place_hold(
                sample_resource.id,
                slot,
                capacity=sample_resource.capacity,
                ttl_seconds=60,
                idempotency_key="expiry-k",
            )

        with time_machine.travel(t0 + timedelta(seconds=61), tick=False):
            second = await backend.place_hold(
                sample_resource.id,
                slot,
                capacity=sample_resource.capacity,
                ttl_seconds=60,
                idempotency_key="expiry-k",
            )

            assert second.id != first.id
            entries = await backend.get_active_entries(sample_resource.id, slot)
            assert second in entries

    async def test_place_hold_idempotent_replay_after_confirm_raises_capacity_exhausted_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # CR-01: once the original Hold has been confirmed into a Booking,
        # a replay must NOT return the stale Hold (which no longer exists in
        # _holds and can never again be confirmed). The slot is still
        # genuinely occupied by the confirmed Booking, so the honest replay
        # outcome is CapacityExhaustedError, not a phantom Hold.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        first = await backend.place_hold(
            sample_resource.id,
            slot,
            capacity=sample_resource.capacity,
            ttl_seconds=60,
            idempotency_key="confirm-k",
        )
        await backend.confirm_hold(first.id, payload={})

        with pytest.raises(CapacityExhaustedError):
            await backend.place_hold(
                sample_resource.id,
                slot,
                capacity=sample_resource.capacity,
                ttl_seconds=60,
                idempotency_key="confirm-k",
            )

    async def test_confirm_hold_idempotent_replay_after_cancel_reflects_live_status_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # CR-01: a confirm_hold replay after the resulting Booking has been
        # cancelled must reflect the LIVE status (CANCELLED), never the
        # frozen CONFIRMED snapshot taken at cache-write time — a consumer
        # retrying the original confirm request must be told the truth.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        hold = await backend.place_hold(
            sample_resource.id, slot, capacity=sample_resource.capacity, ttl_seconds=60
        )
        first = await backend.confirm_hold(
            hold.id, payload={}, idempotency_key="cancel-k"
        )
        assert first.status == BookingStatus.CONFIRMED
        await backend.cancel_booking(first.id)

        second = await backend.confirm_hold(
            hold.id, payload={}, idempotency_key="cancel-k"
        )

        assert second.id == first.id
        assert second.status == BookingStatus.CANCELLED

    async def test_place_hold_idempotency_conflict_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # WR-01: storage-level coverage for the conflict path (previously
        # only exercised via the engine facade in test_engine.py).
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        first_slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )
        second_slot = Interval(
            start=datetime(2026, 9, 7, 16, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 16, 30, tzinfo=UTC),
        )

        await backend.place_hold(
            sample_resource.id,
            first_slot,
            capacity=sample_resource.capacity,
            ttl_seconds=60,
            idempotency_key="conflict-k",
        )

        with pytest.raises(IdempotencyConflictError):
            await backend.place_hold(
                sample_resource.id,
                second_slot,
                capacity=sample_resource.capacity,
                ttl_seconds=60,
                idempotency_key="conflict-k",
            )

    async def test_confirm_hold_idempotent_replay_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # WR-01: storage-level coverage for confirm_hold's basic idempotent
        # replay path (previously only exercised via the engine facade).
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        hold = await backend.place_hold(
            sample_resource.id, slot, capacity=sample_resource.capacity, ttl_seconds=60
        )
        first = await backend.confirm_hold(
            hold.id, payload={"x": 1}, idempotency_key="confirm-replay-k"
        )
        second = await backend.confirm_hold(
            hold.id, payload={"x": 1}, idempotency_key="confirm-replay-k"
        )

        assert first.id == second.id

    async def test_confirm_hold_idempotency_conflict_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # WR-01: storage-level coverage for confirm_hold's conflict path —
        # same idempotency_key with a materially different payload.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        hold = await backend.place_hold(
            sample_resource.id, slot, capacity=sample_resource.capacity, ttl_seconds=60
        )
        await backend.confirm_hold(
            hold.id, payload={"x": 1}, idempotency_key="confirm-conflict-k"
        )

        with pytest.raises(IdempotencyConflictError):
            await backend.confirm_hold(
                hold.id, payload={"x": 2}, idempotency_key="confirm-conflict-k"
            )

    async def test_confirm_hold_idempotent_replay_after_hold_already_deleted_at_storage_level(
        self, backend_factory: type[InMemoryStore], sample_resource: Resource
    ) -> None:
        # WR-01: end-to-end proof of the ordering requirement documented in
        # memory.py's confirm_hold — the idempotency check must run BEFORE
        # the `hold is None` lookup, because a replay's underlying hold has
        # already been deleted by the first call's success. Explicitly
        # asserts the hold is gone from live state before making the second
        # call, so this doesn't silently degrade into a no-op duplicate of
        # test_confirm_hold_idempotent_replay_at_storage_level.
        backend = backend_factory()
        await backend.save_resource(sample_resource)
        slot = Interval(
            start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
            end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
        )

        hold = await backend.place_hold(
            sample_resource.id, slot, capacity=sample_resource.capacity, ttl_seconds=60
        )
        first = await backend.confirm_hold(
            hold.id, payload={}, idempotency_key="deleted-hold-k"
        )

        # 04-01-PLAN.md Task 2: disclosed, minimal cross-backend portability
        # fix — the original assertion here reached into
        # InMemoryStore._holds, a private attribute that structurally
        # cannot exist on SQLStore. A fresh, non-replay confirm_hold call
        # (no idempotency_key) on the same hold_id proves the same fact
        # (the underlying hold row is genuinely gone) without touching a
        # private attribute: it must raise HoldNotFoundError.
        with pytest.raises(HoldNotFoundError):
            await backend.confirm_hold(hold.id, payload={})

        second = await backend.confirm_hold(
            hold.id, payload={}, idempotency_key="deleted-hold-k"
        )

        assert second.id == first.id
