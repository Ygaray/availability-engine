"""Capacity-aware free-fragment computation (AVAIL-01).

This is the primitive that generalizes to capacity >= 1 from day one — Phase
1's own test scope stops at straightforward capacity >= 1 cases; property-
based capacity-K edge-case testing is deferred to Phase 2's AVAIL-02.
"""

from datetime import datetime
from itertools import pairwise

from availability_engine.core.intervals import Interval, intersect


def _sweep_events(busy: list[Interval]) -> list[tuple[datetime, int]]:
    """Build the sorted `(timestamp, delta)` event list for `busy`'s
    start/end boundaries: a `+1` event at each interval's start, a `-1`
    event at each interval's end, sorted so a start at the same instant as
    an end is ordered first (`+1` before `-1`).

    Pure event-list construction only -- shared by `free_fragments` (which
    keeps its own per-segment direct-scan counting logic) and
    `peak_concurrency` (which sweeps this list directly), so the two never
    diverge on how boundary events are built.
    """
    events: list[tuple[datetime, int]] = []
    for b in busy:
        events.append((b.start, 1))
        events.append((b.end, -1))
    # Process +1 (start) before -1 (end) at the same instant.
    events.sort(key=lambda e: (e[0], -e[1]))
    return events


def free_fragments(
    hours: list[Interval], busy: list[Interval], capacity: int
) -> list[tuple[Interval, int]]:
    """For each contiguous sub-interval of `hours` where the number of
    overlapping `busy` intervals is constant, emit
    `(sub_interval, capacity - active_count)`.

    Boundary points are harvested via `busy` interval start/end event
    timestamps (a start/end event pair per `busy` interval, sorted so a
    start at the same instant as an end is ordered first); the count for
    each resulting constant-count segment is then computed directly against
    `busy` (a linear scan per segment, not an incrementally-maintained
    running counter) within each `hours` interval.
    """
    results: list[tuple[Interval, int]] = []

    if not hours:
        return results

    events = _sweep_events(busy)

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
            # CR-02: clamp to 0 rather than letting `remaining` go negative.
            # `active_count <= capacity` normally holds because
            # place_hold's CapacityExhaustedError check prevents accepting
            # more concurrent holds/bookings than a resource's capacity —
            # but that invariant is enforced only at hold-creation time
            # against whatever capacity was current then. A later
            # `define_resource` call that lowers `capacity` below an
            # already-active count is a legal storage write with no
            # corresponding guard, so this primitive must degrade
            # gracefully ("fully booked") instead of emitting a negative
            # `remaining` that crashes `PublicSlot`'s `ge=0` constraint.
            results.append((segment, max(0, capacity - active_count)))

    return results


def peak_concurrency(busy: list[Interval], window: Interval) -> int:
    """The maximum number of `busy` intervals simultaneously active at any
    instant within `window` (ENGINE-02/D-05).

    Reuses `free_fragments`'s own `_sweep_events` event-list construction --
    one shared technique, not a second divergent counting routine. The
    counting algorithm itself differs from `free_fragments`'s per-segment
    direct scan: this is a single scalar running maximum over the swept
    events, clipped to `window`.

    Two correctness properties the naive "scan only in-window event
    timestamps with a per-event running max" approach gets wrong:

    - A `busy` interval that began before `window.start` but is still
      active when the window opens must be counted from the window's
      leading edge onward. Clipping every `busy` interval to `window` via
      `intersect()` before sweeping folds this in correctly -- a raw-event
      sweep restricted to timestamps falling strictly inside `window`
      would miss its start event entirely and undercount.
    - Two intervals that are merely adjacent (one ends exactly when the
      next starts) must never transiently appear as both active. All
      deltas sharing an exact timestamp are netted together into one
      group before being applied to the running count and checked against
      the peak -- checking the peak after each individual event would let
      the first interval's not-yet-applied end and the second's start
      collide at one instant and wrongly show 2.

    Raises `ValueError` if `window` is zero or negative length.
    """
    if window.end <= window.start:
        raise ValueError("window must have positive length")

    clipped = [c for b in busy if (c := intersect(b, window)) is not None]
    if not clipped:
        return 0

    events = _sweep_events(clipped)

    peak = 0
    active = 0
    i = 0
    while i < len(events):
        current_time = events[i][0]
        net_delta = 0
        while i < len(events) and events[i][0] == current_time:
            net_delta += events[i][1]
            i += 1
        active += net_delta
        peak = max(peak, active)

    return peak
