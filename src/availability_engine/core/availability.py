"""Sweep-line capacity-aware free-fragment computation (AVAIL-01).

This is the primitive that generalizes to capacity >= 1 from day one — Phase
1's own test scope stops at straightforward capacity >= 1 cases; property-
based capacity-K edge-case testing is deferred to Phase 2's AVAIL-02.
"""

from datetime import datetime
from itertools import pairwise

from availability_engine.core.intervals import Interval


def free_fragments(
    hours: list[Interval], busy: list[Interval], capacity: int
) -> list[tuple[Interval, int]]:
    """For each contiguous sub-interval of `hours` where the number of
    overlapping `busy` intervals is constant, emit
    `(sub_interval, capacity - active_count)`.

    Sweep-line event-counting: build (time, delta) events from `busy`
    interval boundaries (+1 at start, -1 at end), sweep chronologically
    tracking `active_count`, and emit a fragment for each constant-count
    span within the `hours` intervals.
    """
    results: list[tuple[Interval, int]] = []

    if not hours:
        return results

    events: list[tuple[datetime, int]] = []
    for b in busy:
        events.append((b.start, 1))
        events.append((b.end, -1))
    # Process +1 (start) before -1 (end) at the same instant.
    events.sort(key=lambda e: (e[0], -e[1]))

    for hour_interval in hours:
        # Collect boundary points within this hours interval: the interval's
        # own start/end, plus every busy-event time that falls strictly
        # inside it.
        boundary_times: set[datetime] = {hour_interval.start, hour_interval.end}
        for event_time, _ in events:
            if hour_interval.start < event_time < hour_interval.end:
                boundary_times.add(event_time)
        sorted_times = sorted(boundary_times)

        for seg_start, seg_end in pairwise(sorted_times):
            if seg_start >= seg_end:
                continue
            midpoint = seg_start  # active_count is constant across [seg_start, seg_end)
            active_count = 0
            for b in busy:
                if b.start <= midpoint < b.end:
                    active_count += 1
            segment = Interval(start=seg_start, end=seg_end)
            results.append((segment, capacity - active_count))

    return results
