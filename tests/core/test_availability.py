"""`free_fragments()` capacity-invariant tests (AVAIL-02).

Property-proves `0 <= remaining <= capacity` holds across randomly generated
overlapping busy intervals, plus an explicit exact-boundary example test.
No production code is modified by this file.
"""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from availability_engine.core.availability import free_fragments, peak_concurrency
from availability_engine.core.intervals import Interval

_HOURS_START = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
_HOURS_END = _HOURS_START + timedelta(hours=1)


@given(data=st.data())
def test_free_fragments_never_exceeds_capacity(data: st.DataObject) -> None:
    # `len(busy) <= capacity` is drawn deliberately (not `max_size=6`
    # independent of capacity): at most `capacity` overlapping busy
    # intervals can ever exist at any point in a real system, since
    # engine.py::place_hold's CapacityExhaustedError check already prevents
    # accepting more than `capacity` concurrent holds/bookings for the same
    # resource. Generating more busy intervals than capacity would exercise
    # an out-of-contract input `free_fragments` was never designed to
    # receive (active_count > capacity is prevented upstream, not by this
    # primitive itself) and would falsify the invariant on a scenario the
    # real system can never produce.
    capacity = data.draw(st.integers(min_value=1, max_value=5))
    busy_offsets = data.draw(
        st.lists(
            st.tuples(st.integers(0, 55), st.integers(1, 60)), max_size=capacity
        )
    )

    hours = [Interval(start=_HOURS_START, end=_HOURS_END)]
    busy = [
        Interval(
            start=_HOURS_START + timedelta(minutes=offset),
            end=_HOURS_START + timedelta(minutes=offset + duration),
        )
        for offset, duration in busy_offsets
    ]

    fragments = free_fragments(hours, busy, capacity)

    for _, remaining in fragments:
        assert 0 <= remaining <= capacity


def _remaining_at(
    fragments: list[tuple[Interval, int]], instant: datetime
) -> int:
    """The `remaining` value of whichever fragment segment covers `instant`."""
    return next(
        remaining
        for segment, remaining in fragments
        if segment.start <= instant < segment.end
    )


def test_free_fragments_boundary_exact_capacity() -> None:
    # AVAIL-02's exact boundary case: a point covered by exactly K=3
    # overlapping busy intervals reports remaining == 0 (capacity_exhausted);
    # the same point covered by only K-1=2 of those 3 intervals reports
    # remaining == 1 (one step below max, still available).
    capacity = 3
    hours = [Interval(start=_HOURS_START, end=_HOURS_END)]
    probe_instant = _HOURS_START + timedelta(minutes=15)  # inside [09:10, 09:20)

    # Three busy intervals all covering [09:10, 09:20) — exactly capacity.
    busy_all_three = [
        Interval(start=_HOURS_START, end=_HOURS_START + timedelta(minutes=30)),
        Interval(
            start=_HOURS_START + timedelta(minutes=5),
            end=_HOURS_START + timedelta(minutes=25),
        ),
        Interval(
            start=_HOURS_START + timedelta(minutes=10),
            end=_HOURS_START + timedelta(minutes=20),
        ),
    ]
    fragments_at_capacity = free_fragments(hours, busy_all_three, capacity)
    assert _remaining_at(fragments_at_capacity, probe_instant) == 0

    # Drop the third busy interval — only 2 of the 3 now cover that same
    # instant, so it should report remaining == 1.
    busy_only_two = busy_all_three[:2]
    fragments_one_below = free_fragments(hours, busy_only_two, capacity)
    assert _remaining_at(fragments_one_below, probe_instant) == 1


def test_peak_concurrency_empty_busy_is_zero() -> None:
    window = Interval(start=_HOURS_START, end=_HOURS_END)
    assert peak_concurrency([], window) == 0


def test_peak_concurrency_excludes_non_overlapping_interval() -> None:
    window = Interval(start=_HOURS_START, end=_HOURS_END)
    busy = [
        # Two intervals overlapping each other AND window.
        Interval(
            start=_HOURS_START + timedelta(minutes=5),
            end=_HOURS_START + timedelta(minutes=25),
        ),
        Interval(
            start=_HOURS_START + timedelta(minutes=10),
            end=_HOURS_START + timedelta(minutes=30),
        ),
        # A third interval that does not overlap window at all.
        Interval(
            start=_HOURS_END + timedelta(hours=1),
            end=_HOURS_END + timedelta(hours=2),
        ),
    ]
    assert peak_concurrency(busy, window) == 2


def test_peak_concurrency_counts_interval_active_at_window_start() -> None:
    # Closes the window-boundary undercount gap: an interval that began
    # before window.start but is still active when the window opens must
    # be counted from the window's leading edge onward.
    window = Interval(start=_HOURS_START, end=_HOURS_START + timedelta(hours=1))
    busy = [
        Interval(
            start=_HOURS_START - timedelta(minutes=30),
            end=_HOURS_START + timedelta(minutes=30),
        )
    ]
    assert peak_concurrency(busy, window) == 1


def test_peak_concurrency_adjacent_intervals_never_overcount() -> None:
    # Closes the equal-timestamp overcount gap: two intervals that are
    # merely adjacent (one ends exactly when the next starts) must never
    # transiently show as both active.
    window = Interval(
        start=_HOURS_START - timedelta(hours=1), end=_HOURS_START + timedelta(hours=2)
    )
    busy = [
        Interval(start=_HOURS_START, end=_HOURS_START + timedelta(hours=1)),
        Interval(
            start=_HOURS_START + timedelta(hours=1),
            end=_HOURS_START + timedelta(hours=2),
        ),
    ]
    assert peak_concurrency(busy, window) == 1


def test_peak_concurrency_rejects_nonpositive_window() -> None:
    t = _HOURS_START
    with pytest.raises(ValueError):
        peak_concurrency([], Interval(start=t, end=t))
