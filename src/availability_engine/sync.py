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

# WR-01: bounds every `_call()` dispatch so a call made after `close()`
# (or one that races an in-flight `close()`) fails with a clear
# `TimeoutError` instead of blocking the calling thread forever. 30s is a
# generous upper bound for any single engine operation (in-memory or SQL)
# under normal conditions -- chosen so it never fires on a healthy call,
# only on the actual deadlock class this guards against.
_DEFAULT_CALL_TIMEOUT_SECONDS = 30.0


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

    def _call(
        self,
        coro: Coroutine[Any, Any, _T],
        *,
        timeout: float = _DEFAULT_CALL_TIMEOUT_SECONDS,
    ) -> _T:
        # WR-01: fail fast if the loop isn't there to dispatch onto --
        # e.g. a call made after close() completes (loop stopped and, per
        # IN-02, subsequently closed), or a call racing close() late
        # enough that run_forever() has already returned. Without this,
        # `call_soon_threadsafe` below would still silently schedule a
        # callback that never runs, and `future.result()` would hang the
        # calling thread forever with no exception.
        if self._loop.is_closed() or not self._loop.is_running():
            coro.close()  # avoid a "coroutine was never awaited" warning
            raise RuntimeError("SyncAvailabilityEngine used after close()")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        # Even with the guard above, a call can still race close() in the
        # narrow window between the check and the loop actually stopping
        # -- the explicit timeout bounds that residual race instead of
        # hanging indefinitely.
        return future.result(timeout=timeout)

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
        """Stop the background loop cleanly -- call at consumer shutdown.

        Raises `RuntimeError` if the background thread does not exit
        within the timeout (WR-04) -- silently returning here would
        contradict the documented "stops within a bounded timeout"
        guarantee in the one case (a slow/stuck shutdown) it exists to
        cover.
        """
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError(
                "SyncAvailabilityEngine failed to stop within timeout"
            )
        # IN-02: release the loop's own resources (e.g. selector file
        # descriptors) now that the background thread has actually
        # exited. Only reached on a successful join, so `_call()`'s
        # `is_closed()` guard (WR-01) never races a loop that is still
        # in use.
        self._loop.close()
