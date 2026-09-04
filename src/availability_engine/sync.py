"""Thin synchronous facade over AvailabilityEngine (D-04).

Runs the async engine on a dedicated background thread with its own
persistent event loop, dispatched via `run_coroutine_threadsafe`. This is
deliberately NOT `asyncio.run()` per call: `asyncio.run()` raises
`RuntimeError: asyncio.run() cannot be called from a running event loop`
the first time this facade is invoked from inside a caller that is ITSELF
async and calls this sync API inline (exactly the consumer's documented
calling convention -- see the consumer's `availability/port.py` docstring:
"[the booking core] calls this sync, in-process port inline ... would wrap
it in asyncio.to_thread only if a genuinely blocking real adapter ever
lands" -- i.e. the bridge is this engine's responsibility, not the
caller's).

This module performs zero exception translation or logging (T-05-03):
every `AvailabilityEngine` exception (already payload-free per
`errors.py`'s T-01-01 rule) propagates unchanged through `future.result()`.
Never log or interpolate `payload`/`details` anywhere in this module.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from availability_engine.contracts import (
    AvailabilityResult,
    Booking,
    Hold,
    Resource,
    UtcDatetime,
)
from availability_engine.engine import AvailabilityEngine
from availability_engine.storage.protocol import StorageBackend

_T = TypeVar("_T")


class SyncAvailabilityEngine:
    """Synchronous, thread-safe bridge over `AvailabilityEngine` (D-04).

    Safe to call from any context, including from inside the caller's own
    already-running event loop (Pitfall 3 / Pattern 2) -- unlike a naive
    `asyncio.run()`-per-call wrapper, which raises if a loop is already
    running on the calling thread.

    Call `close()` at consumer shutdown to stop the background thread
    (T-05-04); the thread is a daemon thread, so it will not block process
    exit even if `close()` is never called.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._engine = AvailabilityEngine(storage)
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        # Block until the loop thread signals readiness -- closes the
        # startup race where a caller might invoke a method before the
        # loop exists to dispatch onto.
        self._ready.wait()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _call(self, coro: Coroutine[Any, Any, _T]) -> _T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def define_resource(self, resource: Resource) -> None:
        self._call(self._engine.define_resource(resource))

    def get_availability(
        self, resource_id: str, start: UtcDatetime, end: UtcDatetime
    ) -> AvailabilityResult:
        return self._call(self._engine.get_availability(resource_id, start, end))

    def place_hold(
        self,
        resource_id: str,
        slot_start: UtcDatetime,
        slot_end: UtcDatetime,
        ttl_seconds: int,
        idempotency_key: str | None = None,
    ) -> Hold:
        return self._call(
            self._engine.place_hold(
                resource_id, slot_start, slot_end, ttl_seconds, idempotency_key
            )
        )

    def confirm_hold(
        self,
        hold_id: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Booking:
        return self._call(
            self._engine.confirm_hold(hold_id, payload, idempotency_key)
        )

    def release_hold(self, hold_id: str) -> None:
        self._call(self._engine.release_hold(hold_id))

    def cancel_booking(self, booking_id: str) -> None:
        self._call(self._engine.cancel_booking(booking_id))

    def close(self) -> None:
        """Stop the background loop cleanly -- call at consumer shutdown."""
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
