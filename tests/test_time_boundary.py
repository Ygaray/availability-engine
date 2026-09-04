"""`time.py::localize_operating_hours` midnight-crossing + DST-boundary fixture
tests (GRID-03).

No production code besides `time.py` itself is modified by this file.
"""

from datetime import UTC, datetime, time, timedelta

from availability_engine.contracts import LocalInterval, Resource, Weekday
from availability_engine.time import localize_operating_hours

_TZ = "America/New_York"


def _resource(operating_hours: dict[Weekday, list[LocalInterval]]) -> Resource:
    return Resource(
        id="r1",
        capacity=1,
        operating_hours=operating_hours,
        timezone=_TZ,
        slot_duration=timedelta(minutes=30),
    )


def test_overnight_interval_spans_into_next_calendar_day() -> None:
    """GRID-03: a Monday 22:00->06:00 LocalInterval (end <= start sentinel)
    must produce exactly one UTC Interval spanning Monday 22:00 local through
    Tuesday 06:00 local — an 8-hour UTC span on a non-DST week — not a
    same-day, zero-length, or inverted interval.
    """
    # 2026-06-01 is a Monday, well outside any DST transition window.
    resource = _resource(
        {Weekday.MONDAY: [LocalInterval(start=time(22, 0), end=time(6, 0))]}
    )

    window_start = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 3, 0, 0, tzinfo=UTC)

    intervals = localize_operating_hours(resource, window_start, window_end)

    assert len(intervals) == 1
    interval = intervals[0]
    assert interval.end - interval.start == timedelta(hours=8)
    assert interval.start < interval.end
