"""Tests for `SyncAvailabilityEngine` (D-04) -- the async->sync bridge.

Test D is the load-bearing one: it proves the exact failure mode
05-RESEARCH.md's Pitfall 3 predicted for a naive `asyncio.run()`-per-call
facade (`RuntimeError: asyncio.run() cannot be called from a running event
loop`) does not happen with the `run_coroutine_threadsafe` bridge.
"""

import asyncio
import inspect
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from availability_engine.contracts import AvailabilityResult, Resource
from availability_engine.engine import AvailabilityEngine
from availability_engine.errors import ResourceNotFoundError
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


# 26-10-PLAN.md Task 3: SyncAvailabilityEngine — the ACTUAL chatbot-facing
# facade (via engine_adapter.py, Plan 26-05) — widened with the SAME
# duration/business_id kwargs as the async engine.py.


def test_get_availability_forwards_duration_and_business_id_through_the_same_bridge(
    sample_resource: Resource,
) -> None:
    # Test 2 (the load-bearing proof — closes review's HIGH
    # "SyncAvailabilityEngine is omitted"): calling the sync facade with the
    # new kwargs returns the SAME AvailabilityResult the async engine would
    # for identical arguments against the SAME underlying store — proving
    # the kwargs actually reach the real engine through the SAME
    # run_coroutine_threadsafe bridge every chatbot call uses, not just
    # through engine.py in isolation.
    store = InMemoryStore()
    resource = sample_resource.model_copy(update={"business_id": "biz-a"})
    sync_engine = SyncAvailabilityEngine(store)
    try:
        sync_engine.define_resource(resource)

        sync_result = sync_engine.get_availability(
            resource.id,
            WINDOW_START,
            WINDOW_END,
            duration=timedelta(minutes=60),
            business_id="biz-a",
        )
    finally:
        sync_engine.close()

    async_engine = AvailabilityEngine(store)
    async_result = asyncio.run(
        async_engine.get_availability(
            resource.id,
            WINDOW_START,
            WINDOW_END,
            duration=timedelta(minutes=60),
            business_id="biz-a",
        )
    )

    assert sync_result.available  # sanity: the kwargs actually reached
    assert sync_result == async_result


def test_place_hold_forwards_business_id_through_the_same_bridge(
    sample_resource: Resource,
) -> None:
    # Test 2 (place_hold half of the load-bearing proof): a business_id
    # genuinely reaches the real engine's namespace check through the sync
    # bridge — a hold request under a DIFFERENT business_id for the same
    # resource_id string finds no resource at all.
    store = InMemoryStore()
    resource = sample_resource.model_copy(update={"business_id": "biz-a"})
    sync_engine = SyncAvailabilityEngine(store)
    try:
        sync_engine.define_resource(resource)

        result = sync_engine.get_availability(
            resource.id, WINDOW_START, WINDOW_END, business_id="biz-a"
        )
        slot = result.available[0]

        hold = sync_engine.place_hold(
            resource.id, slot.start, slot.end, ttl_seconds=60, business_id="biz-a"
        )
        assert hold.slot_start == slot.start

        with pytest.raises(ResourceNotFoundError):
            sync_engine.place_hold(
                resource.id,
                slot.start,
                slot.end,
                ttl_seconds=60,
                business_id="biz-b",
            )
    finally:
        sync_engine.close()


def test_get_availability_and_place_hold_v1_call_shapes_unchanged(
    sample_resource: Resource,
) -> None:
    # Test 1 (regression): the existing v1 call shapes, no new kwargs, still
    # work byte-for-byte — this is the EXACT call shape
    # tests/consumers/test_availability_engine_conformance.py's
    # TestRealEngineConformance fixture already uses and must keep passing.
    engine = SyncAvailabilityEngine(InMemoryStore())
    try:
        engine.define_resource(sample_resource)

        result = engine.get_availability(sample_resource.id, WINDOW_START, WINDOW_END)
        slot = result.available[0]

        hold = engine.place_hold(
            sample_resource.id, slot.start, slot.end, ttl_seconds=60
        )
        assert hold.slot_start == slot.start
    finally:
        engine.close()


def test_confirm_release_cancel_signatures_have_no_business_id_param() -> None:
    # Test 3: confirm_hold/release_hold/cancel_booking remain byte-for-byte
    # unchanged (no new kwargs — matching Task 2's D-A decision that these
    # three never gain a business_id parameter anywhere in this phase).
    confirm_params = inspect.signature(SyncAvailabilityEngine.confirm_hold).parameters
    release_params = inspect.signature(SyncAvailabilityEngine.release_hold).parameters
    cancel_params = inspect.signature(SyncAvailabilityEngine.cancel_booking).parameters
    assert "business_id" not in confirm_params
    assert "business_id" not in release_params
    assert "business_id" not in cancel_params
