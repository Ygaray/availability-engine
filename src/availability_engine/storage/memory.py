"""Reference StorageBackend implementation: an asyncio.Lock-guarded
dict-of-dicts in-memory store (Pattern 3).

The check-and-write for `place_hold` happens inside one
`async with self._lock:` block with no intervening `await`, closing the
TOCTOU window (Pitfall 1) even though asyncio is single-threaded.
"""

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from availability_engine.contracts import Booking, BookingStatus, Hold, Resource
from availability_engine.core.intervals import Interval, overlaps
from availability_engine.errors import (
    BookingNotFoundError,
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
    IdempotencyConflictError,
)


def _fingerprint(*parts: object) -> str:
    """Deterministic fingerprint of the call arguments an idempotency key is
    scoped against. `json.dumps(..., sort_keys=True, default=str)` handles
    non-JSON-native parts (e.g. `datetime`) via `str()` deterministically."""
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    fingerprint: str
    result: Hold | Booking


@dataclass
class InMemoryStore:
    _resources: dict[str, Resource] = field(default_factory=dict)
    _holds: dict[str, Hold] = field(default_factory=dict)
    _bookings: dict[str, Booking] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _idempotency: dict[tuple[str, str], IdempotencyRecord] = field(
        default_factory=dict
    )

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
                # explicit release_hold call, or a confirm_hold call that
                # succeeds (i.e. one made *before* expiry — confirm_hold on
                # an already-expired hold raises HoldExpiredError and does
                # NOT delete the record; see confirm_hold below). Either
                # way, it is simply excluded from counting as active on
                # this and every subsequent read regardless of whether the
                # record still exists (IN-01).
                continue
            hold_interval = Interval(start=hold.slot_start, end=hold.slot_end)
            if overlaps(hold_interval, window):
                entries.append(hold)
        for booking in self._bookings.values():
            # Bookings have no expiry, but a cancelled booking (HOLD-06) must
            # never count toward active capacity — same as an expired hold.
            if booking.resource_id != resource_id:
                continue
            if booking.status == BookingStatus.CANCELLED:
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
            # HOLD-07 (D-01/D-02): idempotency check happens first, inside
            # the same critical section as the capacity check/write below —
            # no intervening `await` performs real I/O between the check and
            # the eventual store, closing the TOCTOU window (Pitfall 1).
            # `ttl_seconds` is deliberately EXCLUDED from the fingerprint
            # (Open Question 1) — a legitimate retry may resend a different
            # remaining-timeout budget for the same logical request.
            fp = None
            if idempotency_key is not None:
                fp = _fingerprint(resource_id, slot.start, slot.end)
                existing = self._idempotency.get(("place_hold", idempotency_key))
                if existing is not None:
                    if existing.fingerprint == fp:
                        # IN-02: explicit check (not `assert`) so this
                        # type-narrowing guard survives `python -O`, in case
                        # the (operation_type, key) scoping invariant that
                        # currently prevents cross-type collisions is ever
                        # weakened.
                        if not isinstance(existing.result, Hold):
                            raise TypeError(
                                "place_hold idempotency record does not reference a Hold"
                            )
                        return existing.result
                    raise IdempotencyConflictError("place_hold", idempotency_key)
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
                # Never cache an IdempotencyRecord on this failure path
                # (Pitfall 2/T-03-07) — a retry with the same key, after
                # capacity frees up, must be free to succeed.
                raise CapacityExhaustedError(resource_id, slot)
            hold = Hold(
                id=str(uuid.uuid4()),
                resource_id=resource_id,
                slot_start=slot.start,
                slot_end=slot.end,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
            self._holds[hold.id] = hold
            if idempotency_key is not None:
                assert fp is not None
                self._idempotency[("place_hold", idempotency_key)] = IdempotencyRecord(
                    fp, hold
                )
            return hold

    async def confirm_hold(
        self,
        hold_id: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Booking:
        async with self._lock:
            # HOLD-07: mirrors place_hold's idempotency pattern exactly, but
            # this check must come BEFORE the `hold is None` lookup — a
            # replay's underlying hold may have already been deleted by the
            # first call's success (the exact scenario this replay exists to
            # handle without raising a spurious HoldNotFoundError).
            fp = None
            if idempotency_key is not None:
                fp = _fingerprint(hold_id, payload)
                existing = self._idempotency.get(("confirm_hold", idempotency_key))
                if existing is not None:
                    if existing.fingerprint == fp:
                        # IN-02: explicit check (not `assert`) so this
                        # type-narrowing guard survives `python -O`.
                        if not isinstance(existing.result, Booking):
                            raise TypeError(
                                "confirm_hold idempotency record does not "
                                "reference a Booking"
                            )
                        return existing.result
                    raise IdempotencyConflictError("confirm_hold", idempotency_key)
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
            if idempotency_key is not None:
                assert fp is not None
                self._idempotency[("confirm_hold", idempotency_key)] = (
                    IdempotencyRecord(fp, booking)
                )
            return booking

    async def release_hold(self, hold_id: str) -> None:
        async with self._lock:
            self._holds.pop(hold_id, None)

    async def cancel_booking(self, booking_id: str) -> None:
        async with self._lock:
            booking = self._bookings.get(booking_id)
            if booking is None or booking.status == BookingStatus.CANCELLED:
                # D-04: unlike release_hold's pop-and-ignore idempotent
                # no-op, an unknown or already-cancelled booking_id is
                # always rejected — never a silent no-op.
                raise BookingNotFoundError(booking_id)
            self._bookings[booking_id] = booking.model_copy(
                update={"status": BookingStatus.CANCELLED}
            )
