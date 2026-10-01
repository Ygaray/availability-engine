"""Frozen + half-open unit tests for `core.intervals.Interval` (MODEL-05).

No production code is modified by this file.
"""

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from availability_engine.core.intervals import Interval, overlaps, subtract


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


# 26-10-PLAN.md Task 1 (Round 1 review, MEDIUM "interval subtraction needs
# edge-case tests") -- `subtract()` is a general-purpose primitive; see its
# docstring for why `engine.py::get_availability` deliberately does NOT feed
# its output into grid generation (that would re-anchor the grid).
_DAY_START = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def test_subtract_block_fully_contained_splits_into_two_fragments() -> None:
    hours = [Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=8))]
    block = Interval(
        start=_DAY_START + timedelta(hours=2), end=_DAY_START + timedelta(hours=3)
    )

    result = subtract(hours, [block])

    assert result == [
        Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=2)),
        Interval(
            start=_DAY_START + timedelta(hours=3), end=_DAY_START + timedelta(hours=8)
        ),
    ]


def test_subtract_block_overlapping_leading_edge_leaves_trailing_fragment() -> None:
    hours = [Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=8))]
    block = Interval(
        start=_DAY_START - timedelta(hours=1), end=_DAY_START + timedelta(hours=1)
    )

    result = subtract(hours, [block])

    assert result == [
        Interval(
            start=_DAY_START + timedelta(hours=1), end=_DAY_START + timedelta(hours=8)
        )
    ]


def test_subtract_block_overlapping_trailing_edge_leaves_leading_fragment() -> None:
    hours = [Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=8))]
    block = Interval(
        start=_DAY_START + timedelta(hours=7), end=_DAY_START + timedelta(hours=9)
    )

    result = subtract(hours, [block])

    assert result == [
        Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=7))
    ]


def test_subtract_block_fully_covering_hours_yields_no_fragments() -> None:
    hours = [Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=8))]
    block = Interval(
        start=_DAY_START - timedelta(hours=1), end=_DAY_START + timedelta(hours=9)
    )

    assert subtract(hours, [block]) == []


def test_subtract_adjacent_block_is_a_no_op() -> None:
    # A block that merely touches an hours boundary (no shared point, per
    # the half-open [start, end) semantics) must not remove anything.
    hours = [Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=8))]
    block = Interval(
        start=_DAY_START + timedelta(hours=8), end=_DAY_START + timedelta(hours=9)
    )

    assert subtract(hours, [block]) == hours


def test_subtract_multiple_blocks_fold_against_prior_fragments() -> None:
    # Two disjoint blocks against one hours interval yields three surviving
    # fragments -- each block applied to the previous step's output.
    hours = [Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=8))]
    first_block = Interval(
        start=_DAY_START + timedelta(hours=2), end=_DAY_START + timedelta(hours=3)
    )
    second_block = Interval(
        start=_DAY_START + timedelta(hours=5), end=_DAY_START + timedelta(hours=6)
    )

    result = subtract(hours, [first_block, second_block])

    assert result == [
        Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=2)),
        Interval(
            start=_DAY_START + timedelta(hours=3), end=_DAY_START + timedelta(hours=5)
        ),
        Interval(
            start=_DAY_START + timedelta(hours=6), end=_DAY_START + timedelta(hours=8)
        ),
    ]


def test_subtract_no_blocks_returns_hours_unchanged() -> None:
    hours = [Interval(start=_DAY_START, end=_DAY_START + timedelta(hours=8))]

    assert subtract(hours, []) == hours
