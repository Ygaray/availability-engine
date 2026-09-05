"""Tests for `SyncAvailabilityEngine` (D-04) -- the async->sync bridge.

Test D is the load-bearing one: it proves the exact failure mode
05-RESEARCH.md's Pitfall 3 predicted for a naive `asyncio.run()`-per-call
facade (`RuntimeError: asyncio.run() cannot be called from a running event
loop`) does not happen with the `run_coroutine_threadsafe` bridge.
"""

import asyncio
import threading
import time
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


def test_close_closes_the_underlying_event_loop(sample_resource: Resource) -> None:
    """Test B2 (IN-02): close() releases the loop's own resources, not
    just the thread -- the loop object itself ends up closed()."""
    engine = SyncAvailabilityEngine(InMemoryStore())

    engine.close()

    assert engine._loop.is_closed()


def test_call_after_close_raises_immediately_instead_of_hanging(
    sample_resource: Resource,
) -> None:
    """WR-01 regression: calling a method on the facade after close() has
    completed must raise RuntimeError immediately -- not hang the calling
    thread forever waiting on a callback nothing is left to run. Guarded
    by pytest's default test timeout in spirit; the load-bearing assertion
    is that this call returns (by raising) at all."""
    engine = SyncAvailabilityEngine(InMemoryStore())
    engine.define_resource(sample_resource)
    engine.close()

    with pytest.raises(RuntimeError, match="close"):
        engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)


def test_close_raises_runtime_error_when_thread_fails_to_join_in_time(
    sample_resource: Resource,
) -> None:
    """WR-04 regression: `close()` must raise `RuntimeError` -- not return
    silently -- if the background thread does not exit within its join
    timeout. Exercised with a REAL slow shutdown (a coroutine that blocks
    the event-loop thread itself with a synchronous `time.sleep()` longer
    than the join timeout), not a mocked `Thread.join`/`is_alive` -- this
    is the actual failure class WR-04 exists to surface: `close()` calling
    `loop.stop()` cannot preempt a callback that is currently blocking the
    loop's own thread, so the join genuinely times out."""
    engine = SyncAvailabilityEngine(InMemoryStore())
    engine.define_resource(sample_resource)

    done = threading.Event()

    def blocks_the_loop_thread() -> None:
        # A plain synchronous callback (not a coroutine) blocks the single
        # thread driving this loop's `run_forever()` for real -- scheduled
        # directly via `call_soon_threadsafe` (like `close()`'s own
        # `loop.stop()` callback) so callback ordering is deterministic:
        # both calls are made from this thread in sequence, and
        # `call_soon_threadsafe` callbacks run in FIFO order, so this
        # blocking callback is guaranteed to run BEFORE the `loop.stop()`
        # callback `close()` schedules immediately after.
        time.sleep(8)
        done.set()

    engine._loop.call_soon_threadsafe(blocks_the_loop_thread)

    with pytest.raises(RuntimeError, match="failed to stop"):
        engine.close()

    # Let the real background thread actually finish and exit cleanly so
    # it doesn't leak into other tests.
    assert done.wait(timeout=15)


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
