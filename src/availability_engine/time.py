"""UTC boundary guard + local-operating-hours -> UTC conversion.

Confined here (alongside `contracts.py`'s boundary validator) so `core/` never
needs to import `zoneinfo` directly (Architectural Responsibility Map rule).

Midnight-crossing (`LocalInterval.end <= .start`, D-05's tolerated overnight
sentinel) is handled here: the interval's end is anchored on the following
calendar day. DST transitions need no special-case code — converting each
boundary point independently via `.astimezone(UTC)` before computing the
elapsed span already yields the correct (compressed/expanded) UTC duration
across a spring-forward gap or fall-back doubled hour (GRID-02, verified by
`tests/core/test_grid_dst.py`). A boundary landing *inside* a DST transition
resolves deterministically via Python's default `fold=0` (D-01: collapses
forward through a spring-forward gap; picks the earlier occurrence in a
fall-back doubled hour) — see `tests/test_time_boundary.py`.
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

    # Look back one calendar day so an overnight interval anchored on the
    # prior day (D-05: `end <= start` spills into `current_date + 1`) is
    # always considered, even when the query window itself starts after
    # local midnight (e.g. `place_hold`'s exact-slot window). `intersect()`
    # below already discards anything that doesn't actually overlap the
    # query window, so widening the lookback here is safe (CR-01).
    current_date = start.astimezone(tz).date() - timedelta(days=1)
    end_date = end.astimezone(tz).date()

    while current_date <= end_date:
        weekday = Weekday(current_date.weekday())
        for local_interval in resource.operating_hours.get(weekday, []):
            local_start = datetime.combine(
                current_date, local_interval.start, tzinfo=tz
            )
            # D-05: end <= start is the tolerated overnight sentinel — anchor
            # the end boundary on the following calendar day rather than the
            # start day. A LocalInterval spans at most one midnight-crossing;
            # never current_date + 2.
            interval_end_date = current_date
            if local_interval.end <= local_interval.start:
                interval_end_date = current_date + timedelta(days=1)
            local_end = datetime.combine(
                interval_end_date, local_interval.end, tzinfo=tz
            )
            utc_interval = Interval(
                start=local_start.astimezone(UTC),
                end=local_end.astimezone(UTC),
            )
            clipped = intersect(utc_interval, query_window)
            if clipped is not None:
                intervals.append(clipped)
        current_date += timedelta(days=1)

    return intervals


def localize_blocks(
    resource: Resource, start: datetime, end: datetime
) -> list[Interval]:
    """Convert `resource`'s one-off `BlockInterval` block-outs (D-06) into UTC
    intervals, clipped to the `[start, end)` query window.

    Unlike `localize_operating_hours`, each `BlockInterval` is already a full
    local datetime range (not a time-of-day pair repeated weekly), so no
    date-iteration loop is needed — one boundary-point conversion per block.
    Each boundary point is still converted independently via
    `.astimezone(UTC)` (never a single whole-range UTC conversion computed
    from a local-time duration) so DST transitions compress/expand the UTC
    span correctly, exactly like `localize_operating_hours`.
    """
    tz = ZoneInfo(resource.timezone)
    intervals: list[Interval] = []

    query_window = Interval(start=start, end=end)

    for block in resource.blocks:
        utc_interval = Interval(
            start=block.start.replace(tzinfo=tz).astimezone(UTC),
            end=block.end.replace(tzinfo=tz).astimezone(UTC),
        )
        clipped = intersect(utc_interval, query_window)
        if clipped is not None:
            intervals.append(clipped)

    return intervals
