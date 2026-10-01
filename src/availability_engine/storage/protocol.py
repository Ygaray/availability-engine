"""Coarse-grained async StorageBackend Protocol — frozen forward-compatibly
(D-04). Phase 2/3 params are pre-reserved as defaulted kwargs so the
signature never has to change shape.

26-09-PLAN.md Task 1 (D-08/ENGINE-04, V4 Access Control): this Protocol's 7
methods split into three groups by how they learn their tenant — never one
uniform rule applied inconsistently:

1. `get_resource`/`get_active_entries`/`place_hold` operate on a BARE
   `resource_id` string with no other tenant-carrying context available, so
   they take `business_id` as an explicit FIRST parameter — this IS the
   access-control fix a pre-filtered caller can no longer bypass.
2. `save_resource` operates on a full `Resource` OBJECT that already
   carries `business_id` as a field (Plan 26-06) — it deliberately does
   NOT take a separate `business_id` parameter (a second, disagreeing
   value would be possible otherwise); every implementation derives the
   namespace from `resource.business_id` internally.
3. `confirm_hold`/`release_hold`/`cancel_booking` operate on an already
   globally-unique uuid4 bearer token (`hold_id`/`booking_id`) — a
   `business_id` parameter would be redundant for correctness and is
   deliberately NOT part of these signatures. Where `confirm_hold`'s own
   idempotency-table write needs tenant scoping, it resolves `business_id`
   internally via the permanent `hold_business_index` (SQL table / in-memory
   dict), never from a caller-supplied parameter.

A future reader must not "fix" this three-way split by adding `business_id`
everywhere — it is deliberate, not an oversight.
"""

from typing import Any, Protocol, runtime_checkable

from availability_engine.contracts import Booking, Hold, Resource
from availability_engine.core.intervals import Interval


@runtime_checkable
class StorageBackend(Protocol):
    async def save_resource(self, resource: Resource) -> None:
        """Persist `resource`. `business_id` is NOT a separate parameter —
        every implementation derives the namespace from `resource.business_id`
        (the object already carries it), so a caller can never pass two
        disagreeing values for the same write."""
        ...

    async def get_resource(
        self, business_id: str, resource_id: str
    ) -> Resource | None: ...

    async def get_active_entries(
        self, business_id: str, resource_id: str, window: Interval
    ) -> list[Hold | Booking]: ...

    async def place_hold(
        self,
        business_id: str,
        resource_id: str,
        slot: Interval,
        capacity: int,
        ttl_seconds: int,
        payload: dict[str, Any] | None = None,  # reserved now; Phase 1 may pass None
        idempotency_key: str | None = None,  # reserved for Phase 3 — never rename
    ) -> Hold:
        """Atomically insert iff active count < capacity for this slot.
        Raises CapacityExhaustedError otherwise."""
        ...

    async def confirm_hold(
        self,
        hold_id: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,  # reserved for Phase 3
    ) -> Booking:
        """Atomically transition hold -> booking iff still active and unexpired.
        Raises HoldExpiredError / HoldNotFoundError otherwise. Takes NO
        business_id — resolves its own tenant internally from the permanent
        hold_business_index, never from a caller-supplied parameter (D-A)."""
        ...

    async def release_hold(self, hold_id: str) -> None:
        """Idempotent explicit release. Takes NO business_id (D-A) — hold_id
        is already a globally-unique bearer token."""
        ...

    async def cancel_booking(self, booking_id: str) -> None:
        """NOT idempotent, unlike release_hold's idempotent explicit release.
        Raises BookingNotFoundError on an unknown or already-cancelled
        booking_id (D-04) — cancellation of a booking that is not there to
        cancel is always an error, never a silent no-op. Takes NO
        business_id (D-A) — booking_id is already a globally-unique bearer
        token."""
        ...
