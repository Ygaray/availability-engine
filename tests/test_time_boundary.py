"""`time.py::localize_operating_hours` midnight-crossing + DST-boundary fixture
tests (GRID-03).

No production code besides `time.py` itself is modified by this file.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from availability_engine.contracts import LocalInterval, Resource, Weekday
from availability_engine.time import localize_operating_hours

_TZ = "America/New_York"


def _is_imaginary(dt: datetime, tz: ZoneInfo) -> bool:
    """True iff dt is a nonexistent wall-clock time (falls inside a
    spring-forward gap). Test-local helper, copied verbatim from
    02-RESEARCH.md Pattern 2 — not production code."""
    return dt.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != dt.replace(
        tzinfo=None
    )


def _is_ambiguous(dt: datetime) -> bool:
    """True iff dt occurs twice (falls inside a fall-back doubled hour).
    Test-local helper, copied verbatim from 02-RESEARCH.md Pattern 2 — not
    production code."""
    return dt.replace(fold=0).utcoffset() != dt.replace(fold=1).utcoffset()


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


def test_is_imaginary_detects_spring_forward_gap() -> None:
    tz = ZoneInfo(_TZ)
    gap_time = datetime(2026, 3, 8, 2, 30, tzinfo=tz)
    assert _is_imaginary(gap_time, tz) is True


def test_is_ambiguous_detects_fall_back_doubled_hour() -> None:
    tz = ZoneInfo(_TZ)
    doubled_time = datetime(2026, 11, 1, 1, 30, tzinfo=tz)
    assert _is_ambiguous(doubled_time) is True


def test_boundary_inside_spring_forward_gap_collapses_forward_30_minutes() -> None:
    """D-01: 'skip the non-existent spring-forward hour'. A LocalInterval
    boundary at 02:30 (inside the gap) resolves via Python's default fold=0
    (collapse-forward, per _is_imaginary/D-01) — no exception is raised.

    Verified directly against zoneinfo this session: fold=0 interprets the
    nonexistent 02:30 using the pre-transition (EST, UTC-5) offset, giving
    2026-03-08 07:30:00+00:00 — the same UTC instant as the valid 03:30 EDT
    local time immediately after the gap. local_end (04:00, unambiguous,
    EDT) is 08:00:00+00:00. The resulting UTC span is exactly 30 minutes
    (nominal 90 minutes minus the 60-minute skip), not the naive 90-minute
    span a DST-naive reading would expect, and not a 4-hour span or an
    exception.
    """
    # 2026-03-08 is the real, verified 2026 America/New_York spring-forward
    # date (transition at 02:00 local).
    resource = _resource(
        {Weekday.SUNDAY: [LocalInterval(start=time(2, 30), end=time(4, 0))]}
    )
    window_start = datetime(2026, 3, 8, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 3, 9, 0, 0, tzinfo=UTC)

    intervals = localize_operating_hours(resource, window_start, window_end)

    assert len(intervals) == 1
    assert intervals[0].end - intervals[0].start == timedelta(minutes=30)


def test_boundary_inside_fall_back_doubled_hour_resolves_to_earlier_occurrence() -> (
    None
):
    """D-01/fold=0 default: a LocalInterval boundary at 01:30 (inside the
    fall-back doubled hour) resolves to the earlier (EDT, UTC-4) occurrence,
    not the later (EST, UTC-5) one."""
    # 2026-11-01 is the real, verified 2026 America/New_York fall-back date
    # (transition at 02:00 local).
    tz = ZoneInfo(_TZ)
    resource = _resource(
        {Weekday.SUNDAY: [LocalInterval(start=time(1, 30), end=time(3, 0))]}
    )
    window_start = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)

    intervals = localize_operating_hours(resource, window_start, window_end)

    assert len(intervals) == 1
    expected_start = datetime(2026, 11, 1, 1, 30, tzinfo=tz, fold=0).astimezone(UTC)
    assert intervals[0].start == expected_start
