"""Coarse-grained async StorageBackend Protocol — frozen forward-compatibly
(D-04). Phase 2/3 params are pre-reserved as defaulted kwargs so the
signature never has to change shape.
"""

from typing import Any, Protocol, runtime_checkable

from availability_engine.contracts import Booking, Hold, Resource
from availability_engine.core.intervals import Interval


@runtime_checkable
class StorageBackend(Protocol):
    async def save_resource(self, resource: Resource) -> None: ...

    async def get_resource(self, resource_id: str) -> Resource | None: ...

    async def get_active_entries(
        self, resource_id: str, window: Interval
    ) -> list[Hold | Booking]: ...

    async def place_hold(
        self,
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
        Raises HoldExpiredError / HoldNotFoundError otherwise."""
        ...

    async def release_hold(self, hold_id: str) -> None:
        """Idempotent explicit release."""
        ...
