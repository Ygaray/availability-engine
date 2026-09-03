"""UTC boundary guard + local-operating-hours -> UTC conversion.

Confined here (alongside `contracts.py`'s boundary validator) so `core/` never
needs to import `zoneinfo` directly (Architectural Responsibility Map rule).

Phase 1 scope: same-day local-to-UTC combination only. Midnight-crossing
(`LocalInterval.end < .start`) and DST edge cases are explicitly deferred to
Phase 2 (GRID-02/GRID-03) — do not handle them here.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from availability_engine.contracts import Resource, Weekday
from availability_engine.core.intervals import Interval, intersect


def require_utc(value: datetime) -> datetime:
    """Raise ValueError unless `value` is timezone-aware and exactly UTC.

    For raw-datetime internal call sites not already Pydantic-typed via
    `contracts.UtcDatetime`.
    """
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must be UTC-aware (offset 00:00)")
    return value


def localize_operating_hours(
    resource: Resource, start: datetime, end: datetime
) -> list[Interval]:
    """Convert `resource`'s local operating hours into UTC intervals, clipped
    to the `[start, end)` query window.

    For each calendar date the resource's local timezone touches within the
    window, look up that weekday's `LocalInterval`s, combine each with the
    date and the resource's IANA zone, convert to UTC, then intersect against
    the overall query window.
    """
    tz = ZoneInfo(resource.timezone)
    intervals: list[Interval] = []

    query_window = Interval(start=start, end=end)

    current_date = start.astimezone(tz).date()
    end_date = end.astimezone(tz).date()

    while current_date <= end_date:
        weekday = Weekday(current_date.weekday())
        for local_interval in resource.operating_hours.get(weekday, []):
            local_start = datetime.combine(
                current_date, local_interval.start, tzinfo=tz
            )
            local_end = datetime.combine(current_date, local_interval.end, tzinfo=tz)
            utc_interval = Interval(
                start=local_start.astimezone(UTC),
                end=local_end.astimezone(UTC),
            )
            clipped = intersect(utc_interval, query_window)
            if clipped is not None:
                intervals.append(clipped)
        current_date += timedelta(days=1)

    return intervals
