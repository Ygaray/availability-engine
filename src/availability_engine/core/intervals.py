"""Internal half-open [start, end) interval type and overlap/intersect math.

Zero I/O, zero timezone-awareness — `zoneinfo` is confined to `time.py`
(Architectural Responsibility Map rule). Callers are responsible for passing
already-UTC-aware `datetime` values; this module does no validation of its
own beyond the dataclass's type annotations.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Interval:
    """A half-open [start, end) interval (MODEL-05)."""

    start: datetime
    end: datetime


def overlaps(a: Interval, b: Interval) -> bool:
    """True iff the two half-open intervals share any point in time."""
    return a.start < b.end and b.start < a.end


def intersect(a: Interval, b: Interval) -> Interval | None:
    """The overlapping sub-interval of `a` and `b`, or None if disjoint."""
    if not overlaps(a, b):
        return None
    return Interval(start=max(a.start, b.start), end=min(a.end, b.end))


def subtract(hours: list[Interval], blocked: list[Interval]) -> list[Interval]:
    """Remove every `blocked` sub-range from `hours`, splitting each `hours`
    interval into zero or more surviving fragments.

    26-10-PLAN.md Task 1 (Round 1 review, MEDIUM "interval subtraction needs
    edge-case tests"): handles a block fully contained within an `hours`
    interval (splits into two fragments), a block overlapping only one edge
    (one surviving fragment), a block fully covering an `hours` interval
    (zero surviving fragments), and multiple blocks folded in sequence
    against the same `hours` list (each block applied to the previous
    step's surviving fragments).

    NOTE: this is a general-purpose interval primitive, kept deliberately
    separate from any grid-generation call site. `engine.py`'s
    `get_availability` does NOT feed this function's output into
    `grid.py::grid_slots` — doing so would re-anchor each surviving
    fragment's start to wherever a block boundary fell, rather than to the
    resource's own operating-interval start (D-04's anchoring rule,
    26-10-PLAN.md Cycle-2 fix). `get_availability` instead excludes blocked
    time via a per-candidate overlap filter applied AFTER grid generation.
    `place_hold`, which performs a single hours-containment check (not a
    grid walk), uses this function directly and safely.
    """
    result = list(hours)
    for block in blocked:
        next_result: list[Interval] = []
        for h in result:
            if not overlaps(h, block):
                next_result.append(h)
                continue
            before_end = min(block.start, h.end)
            if before_end > h.start:
                next_result.append(Interval(start=h.start, end=before_end))
            after_start = max(block.end, h.start)
            if after_start < h.end:
                next_result.append(Interval(start=after_start, end=h.end))
        result = next_result
    return result
