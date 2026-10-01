"""DST-transition + window-clipping tests for `time.py::localize_blocks`
(D-06/D-07, GRID-02).

Verifies `localize_blocks` reuses `localize_operating_hours`'s exact
per-boundary-point `.astimezone(UTC)` conversion technique — proven correct
across both DST transition directions on real 2026 `America/New_York`
transition dates, mirroring `tests/core/test_grid_dst.py`'s own fixture/
assertion style. No production code other than `time.py` is modified by
this file.
"""

from datetime import UTC, datetime, timedelta

from availability_engine.contracts import BlockInterval, Resource
from availability_engine.time import localize_blocks

_TZ = "America/New_York"

# Real, verified 2026 America/New_York transition dates (both at 02:00 local).
_SPRING_FORWARD_DATE = datetime(2026, 3, 8)  # Sunday
_FALL_BACK_DATE = datetime(2026, 11, 1)  # Sunday


def _resource(blocks: list[BlockInterval]) -> Resource:
    return Resource(
        id="r1",
        capacity=1,
        operating_hours={},
        timezone=_TZ,
        slot_duration=timedelta(minutes=30),
        blocks=blocks,
    )


def _wide_utc_window() -> tuple[datetime, datetime]:
    """A UTC window guaranteed to cover any block built from the fixture
    dates above, regardless of the resource's local offset."""
    return (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 12, 31, tzinfo=UTC),
    )


def test_block_spring_forward_yields_1_hour() -> None:
    """A 01:00->03:00 local block spanning the spring-forward transition
    (a nonexistent local wall-clock span) converts to a UTC interval whose
    duration reflects the real 1-hour-shorter elapsed time, not a naive
    2-hour assumption."""
    block = BlockInterval(
        start=_SPRING_FORWARD_DATE.replace(hour=1),
        end=_SPRING_FORWARD_DATE.replace(hour=3),
    )
    resource = _resource([block])
    window_start, window_end = _wide_utc_window()

    intervals = localize_blocks(resource, window_start, window_end)

    assert len(intervals) == 1
    assert intervals[0].end - intervals[0].start == timedelta(hours=1)


def test_block_fall_back_yields_3_hours() -> None:
    """A 01:00->03:00 local block spanning the fall-back transition (the
    doubled hour) converts to a UTC interval reflecting the real
    1-hour-longer elapsed span."""
    block = BlockInterval(
        start=_FALL_BACK_DATE.replace(hour=1),
        end=_FALL_BACK_DATE.replace(hour=3),
    )
    resource = _resource([block])
    window_start, window_end = _wide_utc_window()

    intervals = localize_blocks(resource, window_start, window_end)

    assert len(intervals) == 1
    assert intervals[0].end - intervals[0].start == timedelta(hours=3)


def test_block_outside_query_window_yields_empty_list() -> None:
    """A block entirely outside the query window returns an empty list,
    matching localize_operating_hours' own clip-to-window behavior via
    intersect()."""
    block = BlockInterval(
        start=datetime(2026, 6, 1, 9, 0), end=datetime(2026, 6, 1, 10, 0)
    )
    resource = _resource([block])

    intervals = localize_blocks(
        resource,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert intervals == []
