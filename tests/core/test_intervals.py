"""Frozen + half-open unit tests for `core.intervals.Interval` (MODEL-05).

No production code is modified by this file.
"""

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from availability_engine.core.intervals import Interval, overlaps


def test_frozen_and_half_open() -> None:
    a = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    b = a + timedelta(hours=1)
    c = b + timedelta(hours=1)

    interval = Interval(start=a, end=b)
    with pytest.raises(dataclasses.FrozenInstanceError):
        interval.start = c  # type: ignore[misc]

    # Half-open: an interval starting exactly where another ends shares no point.
    first = Interval(start=a, end=b)
    second = Interval(start=b, end=c)
    assert overlaps(first, second) is False
