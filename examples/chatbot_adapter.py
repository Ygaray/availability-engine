"""Reference AvailabilityPort adapter — NOT part of the installed package (D-03).

This is the ONE file in this repo allowed to import `chatbot_engine`. CLAUDE.md's
one-way dependency rule ("engine imports no consumer") applies to
`src/availability_engine/` — this module lives outside that tree specifically so
it structurally cannot violate the rule; the shipped wheel never imports or
depends on `chatbot_engine`.

Demonstrates satisfying the consumer's synchronous `AvailabilityPort` contract
using this engine's `SyncAvailabilityEngine` (D-04). A real consumer either
copies this file into their own composition root or imports it directly as a
worked example — it is proven end to end by
`tests/integration/test_chatbot_conformance.py` subclassing the consumer's
`AvailabilityContractSuite`, but is not itself a separately-versioned public API.

Idempotency-key bookkeeping (`self._hold_keys` / `self._confirmed_keys`) exists
to close a semantics gap between the engine's own idempotency guarantee (a
same-key retry of `place_hold` re-checks live capacity and would otherwise
surface a misleading `CapacityExhaustedError`/`SlotUnavailable` if the original
hold was already confirmed into a booking) and the consumer's richer contract,
which requires that exact retry to raise `HoldConflict` instead (see
`AvailabilityPort.place_hold`'s docstring).

Every id this adapter surfaces (`hold_id`/`booking_id`/`confirmation_ref`) is
the engine's own already-`uuid4()`-generated id, verbatim — never a freshly
minted or predictable value (T-05-05). `confirm_hold` reuses `booking.id` as
both `booking_id` and `confirmation_ref`, which is what makes all three bearer
tokens for a given reservation resolve to the same underlying value, and is
what makes `cancel(ref)` work uniformly regardless of which token the caller
holds.

Exception translation never interpolates `details`/payload content into a
raised consumer exception's message (T-05-06, mirrors `errors.py`'s T-01-01
no-payload-in-constructor rule) — every re-raise below carries no message.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime

from chatbot_engine.availability.port import (
    AvailabilityPort,
    HoldConflict,
    HoldExpired,
    SlotUnavailable,
)
from chatbot_engine.availability.port import (
    Booking as ConsumerBooking,
)
from chatbot_engine.availability.port import (
    Hold as ConsumerHold,
)
from chatbot_engine.availability.port import (
    Slot as ConsumerSlot,
)

from availability_engine.errors import (
    BookingNotFoundError as EngineBookingNotFoundError,
)
from availability_engine.errors import (
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
    IdempotencyConflictError,
    OutsideHoursError,
    ResourceNotFoundError,
)
from availability_engine.sync import SyncAvailabilityEngine


class AvailabilityEngineAdapter(AvailabilityPort):
    """Satisfies `AvailabilityPort` by wrapping a `SyncAvailabilityEngine`."""

    def __init__(self, engine: SyncAvailabilityEngine) -> None:
        self._engine = engine
        # place_hold's idempotency_key -> the hold_id it produced.
        self._hold_keys: dict[str, str] = {}
        # idempotency_keys whose hold has since been confirmed into a
        # booking — distinguishes "genuinely capacity-exhausted retry" from
        # "retry whose original hold was already confirmed" in place_hold's
        # exception-translation below.
        self._confirmed_keys: set[str] = set()
        # WR-02: guards both dicts/sets above. This adapter crosses a
        # thread boundary via SyncAvailabilityEngine, and its own
        # docstring presents it as a copyable production template where a
        # ConversationService may call place_hold/confirm_hold from
        # multiple threads/tasks against the same adapter instance.
        self._keys_lock = threading.Lock()

    def query_availability(
        self, resource_type: str, window: tuple[datetime, datetime], party_size: int
    ) -> list[ConsumerSlot]:
        # v1: single-mapping — resource_type IS the engine's resource_id
        # verbatim, no separate type->id lookup layer.
        result = self._engine.get_availability(resource_type, window[0], window[1])
        slots: list[ConsumerSlot] = []
        for s in result.available:
            if s.remaining < party_size:
                continue
            # Encodes both start AND end (unlike a naive start-only
            # encoding) — place_hold below needs the end time too.
            # WR-03: json.dumps (not an unescaped "|"-joined string) so a
            # resource_id containing "|" (a plausible domain-injected id,
            # since the engine names zero domain concepts and imposes no
            # character restriction on Resource.id) can never desync the
            # inverse split() in place_hold below.
            slot_id = json.dumps(
                [s.resource_id, s.start.isoformat(), s.end.isoformat()]
            )
            slots.append(
                ConsumerSlot(
                    slot_id=slot_id,
                    resource_id=s.resource_id,
                    starts_at=s.start,
                    ends_at=s.end,
                    capacity=s.remaining,
                )
            )
        return slots

    def place_hold(
        self, slot_id: str, ttl_seconds: int, idempotency_key: str
    ) -> ConsumerHold:
        # CR-01: must be checked BEFORE calling the engine at all. The
        # underlying engine only raises on a post-confirm retry when the
        # slot's capacity is *still* exhausted (memory.py's fresh
        # capacity re-check on a missing/consumed Hold) -- for a
        # capacity>1 resource, a confirmed Booking occupies only one
        # unit, so the fresh check can succeed and silently mint a
        # brand-new Hold instead of raising. Checking here makes the
        # behavior independent of live capacity, matching
        # AvailabilityPort.place_hold's documented contract.
        with self._keys_lock:
            if idempotency_key in self._confirmed_keys:
                raise HoldConflict()
        # WR-03: inverse of the json.dumps encoding above -- correctly
        # round-trips a resource_id containing any character, including
        # "|", unlike the old unescaped "|".split("|").
        resource_id, start_iso, end_iso = json.loads(slot_id)
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        try:
            hold = self._engine.place_hold(
                resource_id, start, end, ttl_seconds, idempotency_key=idempotency_key
            )
        except (
            CapacityExhaustedError,
            OutsideHoursError,
            ResourceNotFoundError,
        ) as exc:
            # The post-confirm-retry case is now fully handled by the
            # `_confirmed_keys` check above, before the engine is ever
            # called -- reaching this except block means the key was
            # never confirmed, so a genuine capacity/hours/resource
            # failure always translates to SlotUnavailable.
            raise SlotUnavailable() from exc
        except IdempotencyConflictError as exc:
            # Reused key for a genuinely different slot.
            raise HoldConflict() from exc
        if idempotency_key:
            with self._keys_lock:
                self._hold_keys[idempotency_key] = hold.id
        return ConsumerHold(
            hold_id=hold.id, slot_id=slot_id, expires_at=hold.expires_at
        )

    def confirm_hold(self, hold_id: str, details: dict[str, str]) -> ConsumerBooking:
        try:
            # Passing hold_id itself as the engine's own idempotency key is
            # what gives "repeated confirm_hold(same hold_id) returns the
            # SAME booking" for free, via the engine's existing
            # fingerprint-based idempotency (same hold_id + same details ->
            # same fingerprint -> cached replay).
            booking = self._engine.confirm_hold(
                hold_id, dict(details), idempotency_key=hold_id
            )
        except (HoldExpiredError, HoldNotFoundError) as exc:
            raise HoldExpired() from exc
        with self._keys_lock:
            for key, produced_hold_id in self._hold_keys.items():
                if produced_hold_id == hold_id:
                    self._confirmed_keys.add(key)
        return ConsumerBooking(
            booking_id=booking.id,
            # WR-03: same json.dumps encoding as query_availability's
            # slot_id above, for consistency (this value is opaque to the
            # consumer and never re-parsed in this file, but keeping one
            # encoding scheme avoids reintroducing the unescaped-"|" bug
            # if that ever changes).
            slot_id=json.dumps(
                [
                    booking.resource_id,
                    booking.slot_start.isoformat(),
                    booking.slot_end.isoformat(),
                ]
            ),
            # Reuses the engine's own already-uuid4() booking.id (which,
            # per storage/memory.py, equals the original hold.id) as BOTH
            # booking_id and confirmation_ref, rather than minting a fresh
            # uuid — this is what makes all three bearer tokens the same
            # underlying value for a given reservation.
            confirmation_ref=booking.id,
        )

    def cancel(self, ref: str) -> None:
        try:
            self._engine.cancel_booking(ref)
            return
        except EngineBookingNotFoundError:
            pass
        # Idempotent no-op on any unknown or non-hold id.
        self._engine.release_hold(ref)
