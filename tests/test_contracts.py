"""Boundary-rejection tests for `contracts.py` (MODEL-01/02/04/05, GRID-04).

Proves the public boundary types actually reject the invalid input RESEARCH.md's
Package Legitimacy and Pattern 1 sections call for, closing the gap between "the
tracer's one happy path passes" and "the frozen contract rejects what it must
reject". No production code is modified by this file.
"""

from datetime import UTC, datetime, time, timedelta, timezone

import pydantic
import pytest

from availability_engine.contracts import Hold, LocalInterval, Resource, Weekday


def _base_resource_kwargs() -> dict:
    """Minimal valid Resource kwargs, overridden per-test for the field under test."""
    return {
        "id": "resource-1",
        "capacity": 1,
        "operating_hours": {
            Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(17, 0))],
        },
        "buffer": timedelta(0),
        "timezone": "America/Chicago",
        "slot_duration": timedelta(minutes=30),
    }


def test_resource_capacity_ge_1() -> None:
    kwargs = _base_resource_kwargs()
    kwargs["capacity"] = 0
    with pytest.raises(pydantic.ValidationError):
        Resource(**kwargs)


def test_resource_operating_hours_shape() -> None:
    kwargs = _base_resource_kwargs()
    morning = LocalInterval(start=time(9, 0), end=time(12, 0))
    afternoon = LocalInterval(start=time(13, 0), end=time(17, 0))
    kwargs["operating_hours"] = {Weekday.MONDAY: [morning, afternoon]}

    resource = Resource(**kwargs)

    hours = resource.operating_hours[Weekday.MONDAY]
    assert len(hours) == 2
    assert hours[0].start == time(9, 0)
    assert hours[0].end == time(12, 0)
    assert hours[1].start == time(13, 0)
    assert hours[1].end == time(17, 0)


def test_resource_timezone_validation() -> None:
    kwargs = _base_resource_kwargs()
    kwargs["timezone"] = "Not/AZone"
    with pytest.raises(pydantic.ValidationError):
        Resource(**kwargs)


def test_resource_slot_duration_must_be_positive() -> None:
    # CR-02: slot_duration <= 0 makes grid_slots' step size non-positive,
    # hanging the grid-generation loop forever.
    kwargs = _base_resource_kwargs()
    kwargs["slot_duration"] = timedelta(0)
    with pytest.raises(pydantic.ValidationError):
        Resource(**kwargs)

    kwargs["slot_duration"] = timedelta(minutes=-30)
    with pytest.raises(pydantic.ValidationError):
        Resource(**kwargs)


def test_resource_buffer_cannot_be_negative() -> None:
    # CR-02: a buffer negative enough to cancel out slot_duration makes
    # grid_slots' step size non-positive, hanging the grid-generation loop.
    kwargs = _base_resource_kwargs()
    kwargs["buffer"] = timedelta(minutes=-60)
    with pytest.raises(pydantic.ValidationError):
        Resource(**kwargs)


def test_local_interval_rejects_zero_length() -> None:
    # WR-02: `start == end` used to be silently interpreted by
    # `localize_operating_hours`'s `end <= start` overnight sentinel as a
    # full 24-hour window — the most permissive possible outcome, and almost
    # never what a caller who wrote start==end (e.g. zeroing out a disabled
    # day) actually intended. Reject it loudly at construction time instead.
    with pytest.raises(pydantic.ValidationError):
        LocalInterval(start=time(9, 0), end=time(9, 0))


def test_resource_rejects_overlapping_local_intervals_same_weekday() -> None:
    # WR-01: two overlapping LocalIntervals declared for the same Weekday
    # caused free_fragments to scan (and emit) the overlapping region
    # twice, producing duplicate PublicSlots. Reject at construction time.
    kwargs = _base_resource_kwargs()
    kwargs["operating_hours"] = {
        Weekday.MONDAY: [
            LocalInterval(start=time(9, 0), end=time(12, 0)),
            LocalInterval(start=time(11, 0), end=time(14, 0)),
        ],
    }
    with pytest.raises(pydantic.ValidationError):
        Resource(**kwargs)


def test_resource_rejects_overlapping_overnight_local_intervals() -> None:
    # WR-01, overnight case: two overnight (midnight-crossing) intervals
    # declared for the same weekday that overlap each other on the shared
    # night must also be rejected, not just same-day non-overnight pairs.
    kwargs = _base_resource_kwargs()
    kwargs["operating_hours"] = {
        Weekday.MONDAY: [
            LocalInterval(start=time(22, 0), end=time(2, 0)),
            LocalInterval(start=time(23, 0), end=time(1, 0)),
        ],
    }
    with pytest.raises(pydantic.ValidationError):
        Resource(**kwargs)


def test_resource_allows_adjacent_non_overlapping_local_intervals() -> None:
    # WR-01 regression guard: adjacent (touching, non-overlapping)
    # intervals — the exact split-shift shape D-03 exists to support — must
    # continue to be accepted.
    kwargs = _base_resource_kwargs()
    kwargs["operating_hours"] = {
        Weekday.MONDAY: [
            LocalInterval(start=time(9, 0), end=time(12, 0)),
            LocalInterval(start=time(12, 0), end=time(17, 0)),
        ],
    }
    resource = Resource(**kwargs)
    assert len(resource.operating_hours[Weekday.MONDAY]) == 2


def _base_hold_kwargs() -> dict:
    """Minimal valid Hold kwargs, overridden per-test for the field under test."""
    now_utc = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    return {
        "id": "hold-1",
        "resource_id": "resource-1",
        "slot_start": now_utc,
        "slot_end": now_utc + timedelta(minutes=30),
        "expires_at": now_utc + timedelta(minutes=5),
    }


def test_naive_datetime_rejected() -> None:
    # Naive datetime (no tzinfo at all).
    naive_kwargs = _base_hold_kwargs()
    naive_kwargs["expires_at"] = datetime(2026, 9, 3, 9, 5)
    with pytest.raises(pydantic.ValidationError):
        Hold(**naive_kwargs)

    # Aware but non-UTC offset.
    non_utc_kwargs = _base_hold_kwargs()
    non_utc_kwargs["expires_at"] = datetime(
        2026, 9, 3, 9, 5, tzinfo=timezone(timedelta(hours=5))
    )
    with pytest.raises(pydantic.ValidationError):
        Hold(**non_utc_kwargs)

    # Bare date-only string (the AwareDatetime date-only-string gotcha,
    # github.com/pydantic/pydantic#8859).
    date_only_kwargs = _base_hold_kwargs()
    date_only_kwargs["expires_at"] = "2026-09-03"
    with pytest.raises(pydantic.ValidationError):
        Hold(**date_only_kwargs)
