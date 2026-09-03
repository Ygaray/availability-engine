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
