---
phase: 02-capacity-time-correctness
reviewed: 2026-09-04T04:51:03Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - pyproject.toml
  - src/availability_engine/contracts.py
  - src/availability_engine/engine.py
  - src/availability_engine/errors.py
  - src/availability_engine/storage/memory.py
  - src/availability_engine/time.py
  - tests/core/test_availability.py
  - tests/core/test_grid_dst.py
  - tests/golden/availability_result.schema.json
  - tests/storage/contract_suite.py
  - tests/test_contract_conformance.py
  - tests/test_engine.py
  - tests/test_errors.py
  - tests/test_hold_expiry.py
  - tests/test_time_boundary.py
findings:
  critical: 2
  warning: 2
  info: 1
  total: 5
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-09-04T04:51:03Z
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Reviewed the Phase 2 merge (02-01 midnight-crossing fix, 02-02 lazy hold-expiry fix,
02-03 two-list contract restructure + `ReasonCode`/`OutsideHoursError`) plus their
tests. The already-known cross-plan seam (hold-expiry test slot vs. `OutsideHoursError`)
was fixed correctly and is not re-flagged here.

However, tracing the *actual* interaction between 02-01's midnight-crossing design
(`time.py::localize_operating_hours`) and 02-03's new `OutsideHoursError` check in
`engine.py::place_hold` surfaced a second, unfixed cross-plan integration bug: a hold
request for a slot that `get_availability` itself just reported as available can be
incorrectly rejected as "outside hours" whenever the resource has an overnight
(midnight-crossing) operating-hours interval and the requested slot falls entirely
after local midnight. This was reproduced directly against the merged code (see CR-01).

A second, independent bug was found in the new two-list/capacity contract: reducing a
resource's `capacity` via `define_resource` while holds/bookings already occupy the
prior (higher) capacity causes `get_availability` to crash with an uncaught
`pydantic.ValidationError` rather than a graceful response, because
`core/availability.py::free_fragments`'s `capacity - active_count` can go negative and
`PublicSlot.remaining` has a `ge=0` constraint (CR-02). Both are reproduced with a
runnable script below their write-ups.

Two further, lower-severity gaps were found around unvalidated `LocalInterval`
configurations (overlapping intervals producing duplicate slots; a zero-length interval
silently expanding to a full 24-hour window) and one documentation/behavior mismatch in
`InMemoryStore.confirm_hold`.

## Critical Issues

### CR-01: `OutsideHoursError` false-rejects valid holds on overnight-hours resources when the slot falls after local midnight

**File:** `src/availability_engine/time.py:52-78` (root cause), triggered via `src/availability_engine/engine.py:101-109`

**Issue:** `localize_operating_hours` only ever consults `resource.operating_hours[weekday]` for the calendar date(s) the *query window itself* spans (`current_date = start.astimezone(tz).date()` through `end.astimezone(tz).date()`). It never looks one calendar day back to check whether the *previous* day's `LocalInterval` is an overnight interval (`end <= start`, anchored `+1 day` per D-05) that spills into the window.

`get_availability` is normally called with a window wide enough that this doesn't matter. But `engine.py::place_hold` calls `localize_operating_hours(resource, slot_start, slot_end)` with the query window set to the *exact requested slot* (engine.py:102). For a resource with an overnight `LocalInterval` (e.g. Monday `22:00->06:00`), any hold request whose `[slot_start, slot_end)` falls entirely after local midnight (e.g. Tuesday `05:30-06:00`) resolves `current_date == end_date == Tuesday`, so only `operating_hours[TUESDAY]` is checked — which is empty, since the interval is keyed under `MONDAY`. `hours` comes back empty, `place_hold`'s containment check (`any(h.start <= requested.start ...)`) fails on the empty list, and `OutsideHoursError` is raised — even though `get_availability` had just reported that identical slot as available.

This is a genuine contract break: the two public methods disagree about whether the same slot is available, for any resource that uses overnight hours (the exact scenario D-03's `LocalInterval` list-of-intervals design and 02-01's midnight-crossing fix exist to support). No test in this phase exercises `place_hold` against an overnight-hours resource — `test_place_hold_outside_hours` only tests a same-day resource with a genuinely out-of-hours request.

Reproduced directly against the merged code:
```python
resource = Resource(
    id="night-shift", capacity=1,
    operating_hours={Weekday.MONDAY: [LocalInterval(start=time(22, 0), end=time(6, 0))]},
    timezone="America/Chicago", slot_duration=timedelta(minutes=30),
)
engine = AvailabilityEngine(InMemoryStore())
await engine.define_resource(resource)
result = await engine.get_availability(resource.id, window_start, window_end)
slot = result.available[-1]          # 2026-09-08 10:30 UTC == Tue 05:30 CDT, inside 22:00-06:00
await engine.place_hold(resource.id, slot.start, slot.end, ttl_seconds=60)
# -> OutsideHoursError: slot outside operating hours for resource 'night-shift'
```

**Fix:** Widen the lookback in `localize_operating_hours` by one calendar day so an overnight interval anchored on the prior day is always considered; `intersect()` already discards anything that doesn't actually overlap the query window, so this is safe:
```python
current_date = start.astimezone(tz).date() - timedelta(days=1)
end_date = end.astimezone(tz).date()
```
Add a regression test that mirrors the repro above (place a hold on the after-midnight tail of an overnight-hours resource and assert it succeeds).

### CR-02: Reducing a resource's capacity while holds/bookings are active crashes `get_availability`

**File:** `src/availability_engine/engine.py:71-79` (crash site), `src/availability_engine/storage/memory.py:31-32` (missing guard), `src/availability_engine/contracts.py:121-122` (the constraint that turns the bug into a crash)

**Issue:** `InMemoryStore.save_resource` unconditionally overwrites the stored `Resource`, including its `capacity`, with no check against holds/bookings already occupying the prior capacity. `core/availability.py::free_fragments` computes `remaining = capacity - active_count` using whatever `resource.capacity` currently is; if a resource's capacity is redefined lower than the count of holds/bookings already placed against it, `remaining` goes negative. `engine.py::get_availability` then constructs `PublicSlot(remaining=remaining_capacity, ...)`, and `PublicSlot.remaining` is `Annotated[int, Field(ge=0)]` — so this raises an uncaught `pydantic.ValidationError` out of `get_availability`, not one of the documented `AvailabilityEngineError` subclasses. This is a crash on a read path, not a graceful domain rejection.

Note also `tests/core/test_availability.py`'s hypothesis test explicitly assumes `active_count <= capacity` is "prevented upstream" by `place_hold`'s check — that assumption is true only at hold-*creation* time and is not preserved across a later capacity reduction, so the property test's premise does not actually hold for the system as built.

Reproduced directly against the merged code:
```python
resource = Resource(id="r1", capacity=3, operating_hours={...9-17...}, ...)
await engine.define_resource(resource)
slot = (await engine.get_availability(...)).available[0]
for _ in range(3):
    await engine.place_hold(resource.id, slot.start, slot.end, ttl_seconds=600)  # fills capacity=3
await engine.define_resource(resource.model_copy(update={"capacity": 1}))        # legal capacity edit
await engine.get_availability(resource.id, window_start, window_end)
# -> pydantic_core._pydantic_core.ValidationError: 1 validation error for PublicSlot
#    remaining: Input should be greater than or equal to 0 [input_value=-2]
```

**Fix:** Either (a) reject a `save_resource` capacity decrease that would go below the current active-entry count for that resource (storage-layer guard, consistent with WR-03's "storage is the source of truth for capacity" pattern already used in `place_hold`), or (b) clamp `remaining_capacity` to `max(0, capacity - active_count)` in `core/availability.py::free_fragments` / `engine.py::get_availability` so an inconsistent state degrades to "fully booked" instead of crashing. Add a regression test covering a capacity reduction below the current active-hold count.

## Warnings

### WR-01: Overlapping `LocalInterval`s for the same weekday produce duplicate `PublicSlot`s in the two-list contract

**File:** `src/availability_engine/contracts.py:44-58` (no overlap validation), `src/availability_engine/core/availability.py:40-59` (each `hours` interval scanned independently)

**Issue:** `LocalInterval` has no validation preventing two overlapping intervals from being declared for the same `Weekday` (only same-interval `end <= start` is explicitly tolerated as the overnight sentinel — nothing constrains *different* intervals in the same list from overlapping each other). `free_fragments` iterates `for hour_interval in hours: ...` independently per `hours` entry, with no de-duplication/merge step across entries, so an overlapping region between two declared intervals is scanned — and emitted — twice. `engine.py::get_availability` then appends both to `available`/`booked`, so the response contains duplicate `PublicSlot`s covering the same instant.

Reproduced: a resource with Monday `[09:00-12:00)` and `[11:00-14:00)` (30-minute slot duration, no buffer) yields duplicated slot `start` timestamps at `16:00` and `16:30` UTC in `result.available` (12 slots total, 2 of which are exact duplicates of already-listed slots).

**Fix:** Either add a `Resource`-level validator rejecting overlapping `LocalInterval`s within the same weekday, or merge/de-duplicate `hours` intervals (interval-union) before passing them into `free_fragments`, so the sweep-line only ever sees a partition of non-overlapping windows.

### WR-02: Zero-length `LocalInterval` (`start == end`) silently expands to a full 24-hour window

**File:** `src/availability_engine/time.py:66-67`

**Issue:** The overnight sentinel test is `if local_interval.end <= local_interval.start:` — this is intentional for `end < start` (D-05), but also matches `end == start`. A `LocalInterval(start=time(9,0), end=time(9,0))` — the most natural way to accidentally express "no hours" (e.g. a caller that forgets to set distinct start/end, or zeroes out a disabled day) — is silently interpreted as spanning a full 24 hours (`9:00` on day N through `9:00` on day N+1), the maximally permissive outcome for a scheduling engine, rather than being rejected or treated as empty.

Reproduced: `LocalInterval(start=time(9,0), end=time(9,0))` on Monday produces one UTC interval spanning exactly `1 day, 0:00:00`.

**Fix:** Special-case `end == start` to mean "no hours this day" (skip emitting an interval for it) and reserve the `<` (strictly overnight) case for the wraparound anchor; alternatively, add a validator on `LocalInterval` rejecting `start == end` outright so callers get a loud failure instead of an implicit 24-hour default.

## Info

### IN-01: `InMemoryStore.confirm_hold`'s expired-hold cleanup claim doesn't match its own error path

**File:** `src/availability_engine/storage/memory.py:50-57` (comment), `src/availability_engine/storage/memory.py:110-131` (`confirm_hold`)

**Issue:** The comment on `get_active_entries` states expired holds are lazily excluded "until an explicit `release_hold`/`confirm_hold` call" removes the record. In practice, `confirm_hold` on an already-expired hold takes the `raise HoldExpiredError(hold_id)` branch (memory.py:120-121) and never reaches the `del self._holds[hold_id]` on the next line — so calling `confirm_hold` on an expired hold does not clean up its record; only `release_hold` (or a subsequent write to the same slot elsewhere) does. Correctness is unaffected (expired holds are already excluded from `get_active_entries` regardless of whether the record still exists), but the comment overstates what `confirm_hold` actually does, which could mislead a future maintainer reasoning about `_holds` dict growth.

**Fix:** Tighten the comment to note that `confirm_hold` only removes the record on a *successful* confirmation, not on the `HoldExpiredError` path — or delete the expired record as part of raising `HoldExpiredError` so the comment's claim becomes true.

---

_Reviewed: 2026-09-04T04:51:03Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
