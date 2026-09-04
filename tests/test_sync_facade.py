"""Tests for `SyncAvailabilityEngine` (D-04) -- the async->sync bridge.

Test D is the load-bearing one: it proves the exact failure mode
05-RESEARCH.md's Pitfall 3 predicted for a naive `asyncio.run()`-per-call
facade (`RuntimeError: asyncio.run() cannot be called from a running event
loop`) does not happen with the `run_coroutine_threadsafe` bridge.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from availability_engine.contracts import AvailabilityResult, Resource
from availability_engine.storage.memory import InMemoryStore
from availability_engine.sync import SyncAvailabilityEngine

# 2026-09-07 is a Monday. The window below (UTC) fully covers that Monday's
# calendar date in every timezone, so it always contains sample_resource's
# Monday 09:00-17:00 America/Chicago operating hours (matches test_engine.py).
WINDOW_START = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)


def test_plain_sync_call_sequence(sample_resource: Resource) -> None:
    """Test A: ordinary synchronous code (no running loop) can drive the
    full define -> get_availability -> place_hold -> confirm_hold sequence
    and gets the same real, non-None result shapes the async engine would
    return for the same inputs."""
    engine = SyncAvailabilityEngine(InMemoryStore())
    try:
        engine.define_resource(sample_resource)

        result = engine.get_availability(
            sample_resource.id, WINDOW_START, WINDOW_END
        )
        assert result.available
        assert not result.booked

        first_slot = result.available[0]
        hold = engine.place_hold(
            sample_resource.id, first_slot.start, first_slot.end, ttl_seconds=60
        )
        assert hold.slot_start == first_slot.start
        assert hold.slot_end == first_slot.end

        payload = {"order_id": "abc-123"}
        booking = engine.confirm_hold(hold.id, payload=payload)
        assert booking.payload == payload
    finally:
        engine.close()


def test_close_stops_background_thread(sample_resource: Resource) -> None:
    """Test B: close() joins the background thread within a bounded
    timeout -- no thread leak."""
    engine = SyncAvailabilityEngine(InMemoryStore())
    assert engine._thread.is_alive()

    engine.close()

    assert not engine._thread.is_alive()


def test_naive_datetime_raises_same_boundary_error(
    sample_resource: Resource,
) -> None:
    """Test C: a naive (non-UTC) datetime passed through the sync facade
    still raises the same validation error the async engine raises at its
    own boundary (time_boundary.require_utc) -- the facade adds no
    separate or weaker validation of its own."""
    engine = SyncAvailabilityEngine(InMemoryStore())
    try:
        engine.define_resource(sample_resource)

        naive_start = datetime(2026, 9, 7, 0, 0)  # no tzinfo
        with pytest.raises(ValueError, match="UTC"):
            engine.get_availability(sample_resource.id, naive_start, WINDOW_END)
    finally:
        engine.close()


def test_sync_facade_callable_from_inside_running_event_loop(
    sample_resource: Resource,
) -> None:
    """Test D (load-bearing): calling a SyncAvailabilityEngine synchronous
    method inline from inside an already-running asyncio event loop must
    NOT raise `RuntimeError: asyncio.run() cannot be called from a running
    event loop` -- the exact failure mode a naive asyncio.run()-per-call
    facade would hit here (05-RESEARCH.md Pitfall 3). This mirrors the
    consumer's documented calling convention, where an async
    ConversationService calls the sync port inline, never via
    asyncio.to_thread."""
    engine = SyncAvailabilityEngine(InMemoryStore())
    try:
        # define_resource happens synchronously, outside any running loop.
        engine.define_resource(sample_resource)

        async def caller() -> AvailabilityResult:
            # Inline synchronous call from inside a running event loop --
            # exactly the consumer's calling convention.
            return engine.get_availability(
                sample_resource.id, WINDOW_START, WINDOW_END
            )

        result = asyncio.run(caller())

        assert result.available
    finally:
        engine.close()
