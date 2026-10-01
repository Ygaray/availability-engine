"""AvailabilityEngine facade — the consumer-visible surface (D-04).

The facade never takes a lock itself; atomicity lives entirely behind the
StorageBackend Protocol (STORE-01 structural rule). It calls only Protocol
methods, never a concrete backend.
"""

from typing import Any

from availability_engine import time as time_boundary
from availability_engine.contracts import (
    DEFAULT_BUSINESS_ID,
    AvailabilityResult,
    Booking,
    Hold,
    PublicSlot,
    Resource,
    SlotStatus,
    UtcDatetime,
)
from availability_engine.core.availability import free_fragments
from availability_engine.core.grid import grid_slots
from availability_engine.core.intervals import Interval
from availability_engine.errors import OutsideHoursError, ResourceNotFoundError
from availability_engine.storage.protocol import StorageBackend


class AvailabilityEngine:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    async def define_resource(self, resource: Resource) -> None:
        await self._storage.save_resource(resource)

    async def get_availability(
        self, resource_id: str, start: UtcDatetime, end: UtcDatetime
    ) -> AvailabilityResult:
        # GRID-04 / Success Criterion #5: UtcDatetime is a bare annotation on
        # this plain (non-Pydantic-wrapped) method with zero runtime
        # enforcement — explicitly guard the boundary here rather than rely
        # on an accidental downstream Pydantic construction (see place_hold).
        time_boundary.require_utc(start)
        time_boundary.require_utc(end)

        # 26-09-PLAN.md Task 1 deviation (Rule 3 — blocking issue directly
        # caused by this plan's storage-layer signature change): get_resource
        # and get_active_entries now require business_id as an explicit
        # first parameter. AvailabilityEngine itself has no per-call
        # business_id concept yet — threading a REAL, dynamic business_id
        # through this facade is Plan 26-10's job (per this plan's
        # Protocol Consistency note and threat model: "the engine facade
        # (Plan 26-10) is the caller"). Passing the generic DEFAULT_BUSINESS_ID
        # sentinel here is a deliberate, documented stopgap that keeps
        # today's single-tenant behavior byte-for-byte identical (every
        # Resource saved via this facade already defaults to the same
        # sentinel), not a functional change.
        resource = await self._storage.get_resource(DEFAULT_BUSINESS_ID, resource_id)
        if resource is None:
            # WR-02: match place_hold's unknown-resource handling — both
            # raise the same dedicated error rather than one silently
            # no-oping and the other raising.
            raise ResourceNotFoundError(resource_id)

        hours = time_boundary.localize_operating_hours(resource, start, end)
        window = Interval(start=start, end=end)
        active_entries = await self._storage.get_active_entries(
            DEFAULT_BUSINESS_ID, resource_id, window
        )
        busy = [
            Interval(start=entry.slot_start, end=entry.slot_end)
            for entry in active_entries
        ]

        fragments = free_fragments(hours, busy, resource.capacity)

        available: list[PublicSlot] = []
        booked: list[PublicSlot] = []
        for fragment, remaining_capacity in fragments:
            status = (
                SlotStatus.BOOKED if remaining_capacity <= 0 else SlotStatus.AVAILABLE
            )
            slot_intervals = grid_slots(
                fragment, resource.slot_duration, resource.buffer
            )
            for slot_interval in slot_intervals:
                slot = PublicSlot(
                    start=slot_interval.start,
                    end=slot_interval.end,
                    resource_id=resource_id,
                    status=status,
                    capacity=resource.capacity,
                    remaining=remaining_capacity,
                )
                (available if remaining_capacity > 0 else booked).append(slot)

        return AvailabilityResult(
            resource_id=resource_id, available=available, booked=booked
        )

    async def place_hold(
        self,
        resource_id: str,
        slot_start: UtcDatetime,
        slot_end: UtcDatetime,
        ttl_seconds: int,
        idempotency_key: str | None = None,
    ) -> Hold:
        # 26-09-PLAN.md Task 1 deviation (Rule 3) — see get_availability's
        # identical comment above.
        resource = await self._storage.get_resource(DEFAULT_BUSINESS_ID, resource_id)
        if resource is None:
            raise ResourceNotFoundError(resource_id)
        if slot_end <= slot_start:
            # WR-01: reject inverted/zero-length slots at the boundary,
            # before they're stored as a corrupt-duration Hold/Booking.
            raise ValueError(
                f"slot_end ({slot_end}) must be after slot_start ({slot_start})"
            )
        requested = Interval(start=slot_start, end=slot_end)
        hours = time_boundary.localize_operating_hours(resource, slot_start, slot_end)
        if not any(
            h.start <= requested.start and requested.end <= h.end for h in hours
        ):
            # HOLD-08: a requested hold entirely outside the resource's
            # declared operating hours is rejected here — Phase 1 never
            # performed this check at all (RESEARCH.md verified).
            raise OutsideHoursError(resource_id, requested)
        # 26-09-PLAN.md Task 2 deviation (Rule 3) — place_hold also now
        # requires business_id as its explicit first parameter.
        return await self._storage.place_hold(
            DEFAULT_BUSINESS_ID,
            resource_id,
            requested,
            resource.capacity,
            ttl_seconds,
            idempotency_key=idempotency_key,
        )

    async def confirm_hold(
        self,
        hold_id: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Booking:
        # Never log `payload` anywhere (T-01-01) — it flows only into
        # Booking.payload, untouched.
        return await self._storage.confirm_hold(
            hold_id, payload, idempotency_key=idempotency_key
        )

    async def release_hold(self, hold_id: str) -> None:
        await self._storage.release_hold(hold_id)

    async def cancel_booking(self, booking_id: str) -> None:
        await self._storage.cancel_booking(booking_id)
