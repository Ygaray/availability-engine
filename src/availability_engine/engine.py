"""AvailabilityEngine facade — the consumer-visible surface (D-04).

The facade never takes a lock itself; atomicity lives entirely behind the
StorageBackend Protocol (STORE-01 structural rule). It calls only Protocol
methods, never a concrete backend.
"""

from datetime import timedelta
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
from availability_engine.core.availability import free_fragments, peak_concurrency
from availability_engine.core.grid import grid_slots
from availability_engine.core.intervals import Interval, overlaps, subtract
from availability_engine.errors import OutsideHoursError, ResourceNotFoundError
from availability_engine.storage.protocol import StorageBackend


class AvailabilityEngine:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    async def define_resource(self, resource: Resource) -> None:
        await self._storage.save_resource(resource)

    async def get_availability(
        self,
        resource_id: str,
        start: UtcDatetime,
        end: UtcDatetime,
        *,
        duration: timedelta | None = None,
        business_id: str | None = None,
    ) -> AvailabilityResult:
        # 26-10-PLAN.md Task 1 (D-08/ENGINE-04): resolve the effective
        # tenant FIRST — the ONE decision every storage call for this
        # request threads through. Importing the SAME DEFAULT_BUSINESS_ID
        # constant `Resource.business_id`'s own Pydantic default uses means
        # the two can never silently drift apart (a hardcoded second literal
        # could) — this also supersedes 26-09-PLAN.md's documented stopgap
        # above (that comment described the pre-26-10 state; this facade now
        # has a real per-call business_id concept).
        effective_business_id = (
            business_id if business_id is not None else DEFAULT_BUSINESS_ID
        )

        # GRID-04 / Success Criterion #5: UtcDatetime is a bare annotation on
        # this plain (non-Pydantic-wrapped) method with zero runtime
        # enforcement — explicitly guard the boundary here rather than rely
        # on an accidental downstream Pydantic construction (see place_hold).
        time_boundary.require_utc(start)
        time_boundary.require_utc(end)

        resource = await self._storage.get_resource(effective_business_id, resource_id)
        if resource is None:
            # WR-02: match place_hold's unknown-resource handling — both
            # raise the same dedicated error rather than one silently
            # no-oping and the other raising.
            raise ResourceNotFoundError(resource_id)

        window = Interval(start=start, end=end)
        hours = time_boundary.localize_operating_hours(resource, start, end)
        blocked = time_boundary.localize_blocks(resource, start, end)

        available: list[PublicSlot] = []
        booked: list[PublicSlot] = []

        if duration is None:
            # v1 path — UNTOUCHED pipeline (free_fragments + grid_slots with
            # buffer baked into the step; `hours` is identical to pre-26-10
            # behavior). 26-10-PLAN.md Cycle-2 fix (closes review's MEDIUM
            # "legacy path subtracts blocks before grid generation,
            # re-anchoring slots"): blocked time is excluded as a POST-grid
            # per-candidate filter below, never by subtracting `blocked`
            # from `hours` before free_fragments/grid_slots — doing that
            # would re-anchor grid_slots' per-fragment start to wherever a
            # block boundary fell, the exact D-04 anchoring violation the
            # duration-aware path below is careful to avoid.
            active_entries = await self._storage.get_active_entries(
                effective_business_id, resource_id, window
            )
            busy = [
                Interval(start=entry.slot_start, end=entry.slot_end)
                for entry in active_entries
            ]

            fragments = free_fragments(hours, busy, resource.capacity)
            for fragment, remaining_capacity in fragments:
                status = (
                    SlotStatus.BOOKED
                    if remaining_capacity <= 0
                    else SlotStatus.AVAILABLE
                )
                slot_intervals = grid_slots(
                    fragment, resource.slot_duration, resource.buffer
                )
                for slot_interval in slot_intervals:
                    if any(overlaps(slot_interval, b) for b in blocked):
                        # ENGINE-03: a blocked slot is entirely ABSENT from
                        # both lists — never merely marked unavailable.
                        continue
                    slot = PublicSlot(
                        start=slot_interval.start,
                        end=slot_interval.end,
                        resource_id=resource_id,
                        status=status,
                        capacity=resource.capacity,
                        remaining=remaining_capacity,
                    )
                    (available if remaining_capacity > 0 else booked).append(slot)
        else:
            # Duration-aware path (D-04/D-06/D-07/D-08) — buffer-aware
            # listing via the SAME symmetric peak_concurrency predicate
            # place_hold/store.py uses (never free_fragments' raw-occupancy
            # segmentation — buffer-aware capacity is inherently
            # per-candidate, not per-raw-occupancy-segment).
            #
            # 26-10-PLAN.md Cycle-2 fix (closes review's two HIGH findings:
            # subtracting blocks before grid generation, AND clipping the
            # grid source to the query window, both re-anchor candidate
            # starts to whichever boundary was cut last instead of the
            # resource's own operating-interval start): candidates are laid
            # out from the FULL, unclipped per-day operating interval
            # (`full_hours`, generously day-padded so it is never itself
            # clipped to the narrow real window), anchored at THAT
            # fragment's own start — independent of where the real query
            # window begins or where any block falls. The real query window
            # and `blocked` are both applied as PER-CANDIDATE filters
            # afterward, never as fragment-shaping steps before grid
            # generation:
            #   (a) window CONTAINMENT, not mere overlap (closes review's
            #       HIGH "window filter retains any overlapping candidate
            #       rather than requiring full containment") — a candidate
            #       straddling the window's edge is never offered, since a
            #       caller could never actually hold the portion outside the
            #       window;
            #   (b) block exclusion — a candidate overlapping ANY blocked
            #       interval at all is discarded (conservative: a partial
            #       block overlap still makes the candidate unholdable).
            full_hours = time_boundary.localize_operating_hours(
                resource, start - timedelta(days=1), end + timedelta(days=1)
            )
            fetch_window = Interval(
                start=start - resource.buffer, end=end + resource.buffer
            )
            active_entries = await self._storage.get_active_entries(
                effective_business_id, resource_id, fetch_window
            )
            busy_raw = [
                Interval(start=entry.slot_start, end=entry.slot_end)
                for entry in active_entries
            ]
            padded_busy = [
                Interval(start=b.start, end=b.end + resource.buffer)
                for b in busy_raw
            ]

            for fragment in full_hours:
                candidate_slots = grid_slots(
                    fragment,
                    resource.slot_duration,
                    buffer=timedelta(0),
                    duration=duration,
                )
                for candidate in candidate_slots:
                    if not (
                        candidate.start >= window.start
                        and candidate.end <= window.end
                    ):
                        # (a) full containment in the real query window.
                        continue
                    if any(overlaps(candidate, b) for b in blocked):
                        # (b) per-candidate block exclusion.
                        continue
                    padded_candidate = Interval(
                        start=candidate.start, end=candidate.end + resource.buffer
                    )
                    concurrent_count = peak_concurrency(padded_busy, padded_candidate)
                    remaining = max(0, resource.capacity - concurrent_count)
                    status = (
                        SlotStatus.AVAILABLE if remaining > 0 else SlotStatus.BOOKED
                    )
                    slot = PublicSlot(
                        start=candidate.start,
                        end=candidate.end,
                        resource_id=resource_id,
                        status=status,
                        capacity=resource.capacity,
                        remaining=remaining,
                    )
                    (available if remaining > 0 else booked).append(slot)

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
        *,
        business_id: str | None = None,
    ) -> Hold:
        # 26-10-PLAN.md Task 2: resolve the effective tenant the SAME way
        # get_availability does.
        effective_business_id = (
            business_id if business_id is not None else DEFAULT_BUSINESS_ID
        )
        resource = await self._storage.get_resource(effective_business_id, resource_id)
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
        # 26-10-PLAN.md Task 2 (D-07): subtract blocked time from `hours`
        # BEFORE the containment check below — safe here (unlike
        # get_availability's duration-aware grid, see core/intervals.py's
        # `subtract` docstring) because place_hold performs a single
        # hours-containment check, never a grid walk, so there is no
        # per-fragment anchor for a block boundary to disturb.
        blocked = time_boundary.localize_blocks(resource, slot_start, slot_end)
        hours = subtract(hours, blocked)
        if not any(
            h.start <= requested.start and requested.end <= h.end for h in hours
        ):
            # HOLD-08 + D-07: a requested hold entirely outside the
            # resource's declared operating hours, OR landing inside a
            # blocked range (now absent from `hours` after subtraction), is
            # rejected here with the SAME, closed OUTSIDE_HOURS reason code
            # — D-07 explicitly rejects widening ReasonCode for this.
            raise OutsideHoursError(resource_id, requested)
        # 26-10-PLAN.md Task 2: business_id-threaded per Plan 26-09's
        # storage protocol; buffer padding happens INSIDE this storage call
        # (store.py), never duplicated here (Pitfall 3's explicit scoping).
        return await self._storage.place_hold(
            effective_business_id,
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
