"""RESEARCH.md's Wave 0 gap, closed by 26-10-PLAN.md Task 1: ENGINE-03's full
"never offered AND rejected at hold time" behavior proved end-to-end against
the real `AvailabilityEngine` facade + `InMemoryStore`, not just a unit-level
`contracts.py`/`time.py` test.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from availability_engine.contracts import (
    BlockInterval,
    LocalInterval,
    Resource,
    Weekday,
)
from availability_engine.engine import AvailabilityEngine
from availability_engine.storage.memory import InMemoryStore

# 2026-09-07 is a Monday (matches test_engine.py's WINDOW_START/END).
WINDOW_START = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)

_TZ = ZoneInfo("America/Chicago")


def _resource(resource_id: str, blocks: list[BlockInterval]) -> Resource:
    return Resource(
        id=resource_id,
        capacity=1,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(17, 0))],
        },
        buffer=timedelta(0),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
        blocks=blocks,
    )


async def test_get_availability_excludes_blocked_range_from_available_and_booked() -> (
    None
):
    # The Wave-0 gap: a resource with a BlockInterval covering a 2-hour
    # mid-day range never has those 2 hours appear in EITHER the available
    # OR booked lists — the blocked range is entirely absent, not merely
    # marked unavailable (ENGINE-03).
    resource = _resource(
        "blocked-resource",
        blocks=[
            BlockInterval(
                start=datetime(2026, 9, 7, 12, 0), end=datetime(2026, 9, 7, 14, 0)
            )
        ],
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    result = await engine.get_availability(resource.id, WINDOW_START, WINDOW_END)

    all_slots = result.available + result.booked
    assert all_slots  # sanity: hours outside the block are still offered

    block_start_utc = datetime(2026, 9, 7, 12, 0, tzinfo=_TZ).astimezone(UTC)
    block_end_utc = datetime(2026, 9, 7, 14, 0, tzinfo=_TZ).astimezone(UTC)
    for slot in all_slots:
        overlaps_block = slot.start < block_end_utc and block_start_utc < slot.end
        assert not overlaps_block, (
            f"slot {slot.start}-{slot.end} overlaps the blocked range "
            f"{block_start_utc}-{block_end_utc}"
        )


async def test_get_availability_duration_aware_also_excludes_blocked_range() -> None:
    # Same proof, duration-aware path (duration=30min == slot_duration, so
    # the grid itself is identical to the v1 grid's anchor points) — blocks
    # must be excluded there too, via the per-candidate filter.
    resource = _resource(
        "blocked-resource-duration",
        blocks=[
            BlockInterval(
                start=datetime(2026, 9, 7, 12, 0), end=datetime(2026, 9, 7, 14, 0)
            )
        ],
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(resource)

    result = await engine.get_availability(
        resource.id, WINDOW_START, WINDOW_END, duration=timedelta(minutes=30)
    )

    all_slots = result.available + result.booked
    assert all_slots

    block_start_utc = datetime(2026, 9, 7, 12, 0, tzinfo=_TZ).astimezone(UTC)
    block_end_utc = datetime(2026, 9, 7, 14, 0, tzinfo=_TZ).astimezone(UTC)
    for slot in all_slots:
        overlaps_block = slot.start < block_end_utc and block_start_utc < slot.end
        assert not overlaps_block


async def test_legacy_path_blocks_present_vs_absent_same_anchor_points() -> None:
    # 26-10-PLAN.md Cycle-2 fix (closes review's MEDIUM "legacy duration=None
    # path subtracts blocks before grid generation, re-anchoring slots
    # against D-04's defined anchoring rule"): the SAME resource/window,
    # with and without a non-grid-aligned block, must produce slots at
    # IDENTICAL anchor points wherever both runs still offer a slot — fewer
    # available slots when blocked, never shifted ones.
    no_block_resource = _resource("no-block-resource", blocks=[])
    blocked_resource = _resource(
        "blocked-resource-anchor",
        blocks=[
            BlockInterval(
                # 10:00-10:40 local — ends at a NON-grid-aligned instant
                # relative to the 09:00-anchored 30-minute grid.
                start=datetime(2026, 9, 7, 10, 0),
                end=datetime(2026, 9, 7, 10, 40),
            )
        ],
    )
    engine = AvailabilityEngine(InMemoryStore())
    await engine.define_resource(no_block_resource)
    await engine.define_resource(blocked_resource)

    no_block_result = await engine.get_availability(
        no_block_resource.id, WINDOW_START, WINDOW_END
    )
    blocked_result = await engine.get_availability(
        blocked_resource.id, WINDOW_START, WINDOW_END
    )

    no_block_starts = {
        s.start for s in no_block_result.available + no_block_result.booked
    }
    blocked_starts = {
        s.start for s in blocked_result.available + blocked_result.booked
    }

    # Fewer slots when blocked...
    assert len(blocked_starts) < len(no_block_starts)
    # ...but every surviving slot's start is one of the no-blocks run's own
    # anchor points — never shifted to the block's own (off-grid) end.
    assert blocked_starts.issubset(no_block_starts)

    block_end_utc = datetime(2026, 9, 7, 10, 40, tzinfo=_TZ).astimezone(UTC)
    assert block_end_utc not in blocked_starts  # never re-anchored to 10:40

    # Resumes at the next ALIGNED grid point (11:00 local), present in BOTH
    # runs (same anchor).
    resumed_start = datetime(2026, 9, 7, 11, 0, tzinfo=_TZ).astimezone(UTC)
    assert resumed_start in blocked_starts
    assert resumed_start in no_block_starts
