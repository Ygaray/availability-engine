"""Reference StorageBackend implementation: an asyncio.Lock-guarded
dict-of-dicts in-memory store (Pattern 3).

The check-and-write for `place_hold` happens inside one
`async with self._lock:` block with no intervening `await`, closing the
TOCTOU window (Pitfall 1) even though asyncio is single-threaded.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from availability_engine.contracts import Booking, Hold, Resource
from availability_engine.core.intervals import Interval, overlaps
from availability_engine.errors import (
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
)


@dataclass
class InMemoryStore:
    _resources: dict[str, Resource] = field(default_factory=dict)
    _holds: dict[str, Hold] = field(default_factory=dict)
    _bookings: dict[str, Booking] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def save_resource(self, resource: Resource) -> None:
        self._resources[resource.id] = resource

    async def get_resource(self, resource_id: str) -> Resource | None:
        return self._resources.get(resource_id)

    async def get_active_entries(
        self, resource_id: str, window: Interval
    ) -> list[Hold | Booking]:
        # AVAIL-03/HOLD-05: this is the ONE shared, expiry-filtering
        # active-entries primitive — every read and write path that needs to
        # know what currently occupies capacity calls this, never a
        # duplicate scan (the original Phase 1 gap was exactly two
        # un-synchronized scans, neither of which checked expiry).
        now = datetime.now(UTC)
        entries: list[Hold | Booking] = []
        for hold in self._holds.values():
            if hold.resource_id != resource_id:
                continue
            if hold.expires_at <= now:
                # Active iff expires_at > now — the same predicate
                # confirm_hold already uses correctly below. Lazy release:
                # the expired Hold record stays in _holds (HOLD-05) until an
                # explicit release_hold/confirm_hold call; it is simply
                # excluded from counting as active on this and every
                # subsequent read.
                continue
            hold_interval = Interval(start=hold.slot_start, end=hold.slot_end)
            if overlaps(hold_interval, window):
                entries.append(hold)
        for booking in self._bookings.values():
            # Bookings have no expiry — cancellation is Phase 3's HOLD-06,
            # out of scope here.
            if booking.resource_id != resource_id:
                continue
            booking_interval = Interval(start=booking.slot_start, end=booking.slot_end)
            if overlaps(booking_interval, window):
                entries.append(booking)
        return entries

    async def place_hold(
        self,
        resource_id: str,
        slot: Interval,
        capacity: int,
        ttl_seconds: int,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Hold:
        async with self._lock:
            # WR-03: re-read the authoritative capacity from our own store
            # under the lock rather than trusting the caller-supplied
            # snapshot — closes the race where a concurrent
            # `define_resource` changes capacity between the caller's read
            # and this lock acquisition. Fall back to the caller-supplied
            # `capacity` only if the resource isn't tracked here (shouldn't
            # happen via the engine facade, which already validates it).
            resource = self._resources.get(resource_id)
            effective_capacity = resource.capacity if resource is not None else capacity
            # get_active_entries() performs zero real I/O (pure dict
            # iteration, no internal suspension point) — awaiting it from
            # inside this async with self._lock: block does not yield
            # control back to the event loop, so it does not reopen the
            # TOCTOU window the check-and-write pattern above guards
            # against. Reusing the one shared primitive here (instead of a
            # second, separate scan) is exactly what AVAIL-03 requires.
            active = await self.get_active_entries(resource_id, slot)
            if len(active) >= effective_capacity:
                raise CapacityExhaustedError(resource_id, slot)
            hold = Hold(
                id=str(uuid.uuid4()),
                resource_id=resource_id,
                slot_start=slot.start,
                slot_end=slot.end,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
            self._holds[hold.id] = hold
            return hold

    async def confirm_hold(
        self,
        hold_id: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Booking:
        async with self._lock:
            hold = self._holds.get(hold_id)
            if hold is None:
                raise HoldNotFoundError(hold_id)
            if datetime.now(UTC) >= hold.expires_at:
                raise HoldExpiredError(hold_id)
            del self._holds[hold_id]
            booking = Booking(
                id=hold.id,
                resource_id=hold.resource_id,
                slot_start=hold.slot_start,
                slot_end=hold.slot_end,
                payload=payload if payload is not None else {},
            )
            self._bookings[booking.id] = booking
            return booking

    async def release_hold(self, hold_id: str) -> None:
        async with self._lock:
            self._holds.pop(hold_id, None)
