"""AvailabilityEngine facade — the consumer-visible surface (D-04).

The facade never takes a lock itself; atomicity lives entirely behind the
StorageBackend Protocol (STORE-01 structural rule). It calls only Protocol
methods, never a concrete backend.
"""

from typing import Any

from availability_engine import time as time_boundary
from availability_engine.contracts import (
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
from availability_engine.storage.protocol import StorageBackend


class AvailabilityEngine:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    async def define_resource(self, resource: Resource) -> None:
        await self._storage.save_resource(resource)

    async def get_availability(
        self, resource_id: str, start: UtcDatetime, end: UtcDatetime
    ) -> AvailabilityResult:
        resource = await self._storage.get_resource(resource_id)
        if resource is None:
            return AvailabilityResult(resource_id=resource_id, slots=[])

        hours = time_boundary.localize_operating_hours(resource, start, end)
        window = Interval(start=start, end=end)
        active_entries = await self._storage.get_active_entries(resource_id, window)
        busy = [
            Interval(start=entry.slot_start, end=entry.slot_end)
            for entry in active_entries
        ]

        fragments = free_fragments(hours, busy, resource.capacity)

        slots: list[PublicSlot] = []
        for fragment, remaining_capacity in fragments:
            status = (
                SlotStatus.BOOKED if remaining_capacity <= 0 else SlotStatus.AVAILABLE
            )
            slot_intervals = grid_slots(
                fragment, resource.slot_duration, resource.buffer
            )
            for slot_interval in slot_intervals:
                slots.append(
                    PublicSlot(
                        start=slot_interval.start,
                        end=slot_interval.end,
                        resource_id=resource_id,
                        status=status,
                    )
                )

        return AvailabilityResult(resource_id=resource_id, slots=slots)

    async def place_hold(
        self,
        resource_id: str,
        slot_start: UtcDatetime,
        slot_end: UtcDatetime,
        ttl_seconds: int,
    ) -> Hold:
        resource = await self._storage.get_resource(resource_id)
        if resource is None:
            raise ValueError(f"resource {resource_id!r} not found")
        if slot_end <= slot_start:
            # WR-01: reject inverted/zero-length slots at the boundary,
            # before they're stored as a corrupt-duration Hold/Booking.
            raise ValueError(
                f"slot_end ({slot_end}) must be after slot_start ({slot_start})"
            )
        interval = Interval(start=slot_start, end=slot_end)
        return await self._storage.place_hold(
            resource_id, interval, resource.capacity, ttl_seconds
        )

    async def confirm_hold(self, hold_id: str, payload: dict[str, Any]) -> Booking:
        # Never log `payload` anywhere (T-01-01) — it flows only into
        # Booking.payload, untouched.
        return await self._storage.confirm_hold(hold_id, payload)

    async def release_hold(self, hold_id: str) -> None:
        await self._storage.release_hold(hold_id)
