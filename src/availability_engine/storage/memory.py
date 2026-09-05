"""Reference StorageBackend implementation: an asyncio.Lock-guarded
dict-of-dicts in-memory store (Pattern 3).

The check-and-write for `place_hold` happens inside one
`async with self._lock:` block with no intervening `await`, closing the
TOCTOU window (Pitfall 1) even though asyncio is single-threaded.
"""

import asyncio
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
from availability_engine.storage._shared import _fingerprint

# WR-02: _fingerprint now lives in storage._shared — both this module and
# sql/store.py import it from there, making the cross-backend idempotency
# contract explicit rather than one module depending on the other's
# "private" helper.


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
    # IN-01: no TTL/eviction — records accumulate for the process lifetime.
    # Not a correctness bug for this reference in-memory store (and out of
    # v1 performance scope), but the future SQL backend (Phase 4) will need
    # an explicit retention/cleanup policy for the equivalent table, since
    # an unbounded idempotency table has real operational cost there.
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
        # WR-04: `payload` is currently a no-op here — it is accepted (to
        # match the StorageBackend Protocol's reserved-kwarg signature) but
        # never attached to the resulting Hold or carried through to the
        # eventual Booking. Only confirm_hold's `payload` is actually stored.
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
                                "place_hold idempotency record does not "
                                "reference a Hold"
                            )
                        # CR-01: re-validate against live state before
                        # trusting the cached snapshot — the referenced Hold
                        # may since have been consumed by confirm_hold,
                        # explicitly released, or simply expired. A stale
                        # record must never be returned verbatim (it would
                        # describe a Hold that no longer exists, and would
                        # permanently strand this key). Fall through to
                        # re-run the real check-and-write below, which either
                        # creates a fresh Hold (capacity now free) or
                        # correctly raises CapacityExhaustedError (capacity
                        # still occupied, e.g. by the confirmed Booking) —
                        # either outcome reflects live state, unlike the
                        # frozen replay.
                        live = self._holds.get(existing.result.id)
                        if live is not None and live.expires_at > datetime.now(UTC):
                            return live
                    else:
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
                if payload is not None:
                    try:
                        json.dumps(payload, sort_keys=True)
                    except TypeError as exc:
                        # WR-02: fail fast with a clear error rather than
                        # silently falling back to _fingerprint's
                        # `default=str` for non-JSON-native payload values —
                        # str() of an arbitrary object (e.g. default object
                        # repr, a set's insertion-order-dependent repr) is
                        # not guaranteed to be a pure function of the
                        # payload's logical value, which could otherwise
                        # misclassify a legitimate retry as a conflict.
                        raise TypeError(
                            "confirm_hold payload must be JSON-serializable "
                            "with stable-value semantics for idempotency "
                            "fingerprinting"
                        ) from exc
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
                        # CR-01: always return the live record, not the
                        # frozen snapshot — the cached Booking's status is
                        # stale if it was subsequently cancelled via
                        # cancel_booking. Falls back to the snapshot only if
                        # the id has somehow been removed from _bookings
                        # (never happens today — bookings are never deleted,
                        # only status-transitioned — but this keeps the
                        # replay safe if that ever changes).
                        return self._bookings.get(existing.result.id, existing.result)
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
