"""DST-transition fixture tests on real 2026 `America/New_York` transition
dates (GRID-02).

Verifies that `time_boundary.localize_operating_hours`'s existing
boundary-conversion design (localize each boundary point independently via
`.astimezone(UTC)`, no DST-aware code in the grid stepper) already produces
the correct, DST-compressed/expanded UTC span. No production code is
modified by this file.
"""

from datetime import UTC, datetime, time, timedelta

from availability_engine.contracts import LocalInterval, Resource, Weekday
from availability_engine.time import localize_operating_hours

_TZ = "America/New_York"

# Real, verified 2026 America/New_York transition dates (both at 02:00 local).
_SPRING_FORWARD = datetime(2026, 3, 8, tzinfo=UTC)  # Sunday
_FALL_BACK = datetime(2026, 11, 1, tzinfo=UTC)  # Sunday


def _resource(operating_hours: dict[Weekday, list[LocalInterval]]) -> Resource:
    return Resource(
        id="r1",
        capacity=1,
        operating_hours=operating_hours,
        timezone=_TZ,
        slot_duration=timedelta(minutes=30),
    )


def _weekday_for(date_only: datetime) -> Weekday:
    return Weekday(date_only.weekday())


def _query_window(date_only: datetime) -> tuple[datetime, datetime]:
    """A UTC window guaranteed to cover the given local calendar date and the
    one after it, regardless of the resource's local offset."""
    return date_only - timedelta(days=1), date_only + timedelta(days=2)


def test_overnight_window_spring_forward_yields_7_hours() -> None:
    """An overnight 22:00->06:00 LocalInterval anchored the day before
    spring-forward crosses the skipped hour: nominal 8h, actual 7h UTC."""
    day_before = _SPRING_FORWARD - timedelta(days=1)
    resource = _resource(
        {_weekday_for(day_before): [LocalInterval(start=time(22, 0), end=time(6, 0))]}
    )
    window_start, window_end = _query_window(day_before)

    intervals = localize_operating_hours(resource, window_start, window_end)

    assert len(intervals) == 1
    assert intervals[0].end - intervals[0].start == timedelta(hours=7)


def test_overnight_window_fall_back_yields_9_hours() -> None:
    """An overnight 22:00->06:00 LocalInterval anchored the day before
    fall-back crosses the doubled hour: nominal 8h, actual 9h UTC."""
    day_before = _FALL_BACK - timedelta(days=1)
    resource = _resource(
        {_weekday_for(day_before): [LocalInterval(start=time(22, 0), end=time(6, 0))]}
    )
    window_start, window_end = _query_window(day_before)

    intervals = localize_operating_hours(resource, window_start, window_end)

    assert len(intervals) == 1
    assert intervals[0].end - intervals[0].start == timedelta(hours=9)


def test_midnight_boundary_only_spring_forward_yields_3_hours() -> None:
    """A midnight-anchored 00:00->04:00 LocalInterval on spring-forward
    itself: nominal 4h, actual 3h UTC (the skipped hour)."""
    resource = _resource(
        {
            _weekday_for(_SPRING_FORWARD): [
                LocalInterval(start=time(0, 0), end=time(4, 0))
            ]
        }
    )
    window_start, window_end = _query_window(_SPRING_FORWARD)

    intervals = localize_operating_hours(resource, window_start, window_end)

    assert len(intervals) == 1
    assert intervals[0].end - intervals[0].start == timedelta(hours=3)


def test_midnight_boundary_only_fall_back_yields_5_hours() -> None:
    """A midnight-anchored 00:00->04:00 LocalInterval on fall-back itself:
    nominal 4h, actual 5h UTC (the doubled hour)."""
    resource = _resource(
        {_weekday_for(_FALL_BACK): [LocalInterval(start=time(0, 0), end=time(4, 0))]}
    )
    window_start, window_end = _query_window(_FALL_BACK)

    intervals = localize_operating_hours(resource, window_start, window_end)

    assert len(intervals) == 1
    assert intervals[0].end - intervals[0].start == timedelta(hours=5)
