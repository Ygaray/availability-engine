---
phase: 01-end-to-end-walking-skeleton-in-memory
reviewed: 2026-09-03T00:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - src/availability_engine/__init__.py
  - src/availability_engine/contracts.py
  - src/availability_engine/core/__init__.py
  - src/availability_engine/core/availability.py
  - src/availability_engine/core/grid.py
  - src/availability_engine/core/intervals.py
  - src/availability_engine/engine.py
  - src/availability_engine/errors.py
  - src/availability_engine/storage/__init__.py
  - src/availability_engine/storage/memory.py
  - src/availability_engine/storage/protocol.py
  - src/availability_engine/time.py
  - tests/conftest.py
  - tests/core/__init__.py
  - tests/core/test_grid.py
  - tests/core/test_intervals.py
  - tests/storage/__init__.py
  - tests/storage/contract_suite.py
  - tests/storage/test_protocol_conformance.py
  - tests/test_contracts.py
  - tests/test_engine.py
  - pyproject.toml
findings:
  critical: 2
  warning: 3
  info: 3
  total: 8
status: resolved
---

# Phase 01: Code Review Report

**Reviewed:** 2026-09-03T00:00:00Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Reviewed the Phase 1 walking-skeleton implementation: contracts, interval/grid/availability
core math, the `AvailabilityEngine` facade, the in-memory `StorageBackend` reference impl, and
the test suite. The TOCTOU-closing pattern for `place_hold`/`confirm_hold` (single
`async with self._lock:` block, zero intervening `await`) is implemented correctly, half-open
interval semantics are correct and tested, the UTC-boundary Pydantic validator correctly rejects
naive/non-UTC/date-only input, and the opaque-payload-never-in-exceptions rule is honestly
followed (`CapacityExhaustedError`/`HoldExpiredError`/`HoldNotFoundError` only ever carry
identifiers).

However, two Critical defects were found. Most importantly, hold TTL expiry is checked in
exactly one place (`confirm_hold`) and is never enforced on the read paths that the project's own
locked design ("lazy-on-read expiry, no background sweeper") requires — `_count_active` and
`get_active_entries` never filter expired holds, so an unconfirmed/unreleased hold permanently
occupies capacity and permanently renders its slot `BOOKED` in `get_availability`, forever, even
long after its TTL has elapsed. Separately, `grid_slots` has no floor on `slot_duration`/`buffer`
and will hang in an infinite loop if a `Resource` is constructed with `slot_duration <= 0` or a
buffer negative enough to make the step size non-positive — nothing in `contracts.py` prevents a
consumer from constructing such a `Resource`.

## Critical Issues

### CR-01: Expired holds are never excluded from capacity/availability — lazy-expiry design is unimplemented

**File:** `src/availability_engine/storage/memory.py:37-53` (`get_active_entries`), `:55-69` (`_count_active`), `:94-115` (`confirm_hold`)

**Issue:** The project's locked design (documented in the project's own CLAUDE.md "What NOT to
Use" table) explicitly rejects a background sweeper in favor of "Check-and-lazily-expire on every
read path that touches a hold." That lazy-expiry check is implemented in exactly one place —
`confirm_hold` (line 104) — and even there it only raises `HoldExpiredError`; it does **not**
remove the expired hold from `self._holds` (no `del self._holds[hold_id]` on the expiry branch,
contrast with the success path at line 106).

`_count_active` (used by `place_hold` to enforce capacity) and `get_active_entries` (used by
`get_availability` to compute busy intervals) both iterate `self._holds.values()`
unconditionally, with no `expires_at` check at all. The practical effect:

1. A hold that is placed but never confirmed or released continues to count against capacity
   forever after its TTL elapses — `place_hold` for any overlapping slot will keep raising
   `CapacityExhaustedError` indefinitely.
2. `get_availability` will keep reporting that slot as `SlotStatus.BOOKED` indefinitely, long
   after the hold has expired.
3. There is no test in `tests/test_engine.py` or `tests/storage/contract_suite.py` that exercises
   TTL expiry at all (only explicit `release_hold` is tested) — this gap in test coverage let the
   missing behavior ship.

This is not a deferred-to-Phase-2 item; `ttl_seconds`, `Hold.expires_at`, and the
`HoldExpiredError` check already exist in Phase 1, so the feature is half-built. A resource whose
consumer never confirms or releases a hold before it expires becomes permanently unbookable for
that slot — a direct violation of the "atomic, correct availability" core value.

**Fix:** Filter (and, opportunistically, purge) expired holds on every read/write path that
inspects `self._holds`:
```python
def _is_active(self, hold: Hold, now: datetime) -> bool:
    return hold.expires_at > now

async def get_active_entries(
    self, resource_id: str, window: Interval
) -> list[Hold | Booking]:
    now = datetime.now(UTC)
    entries: list[Hold | Booking] = []
    for hold in list(self._holds.values()):
        if hold.resource_id != resource_id or not self._is_active(hold, now):
            continue
        ...

def _count_active(self, resource_id: str, slot: Interval) -> int:
    now = datetime.now(UTC)
    count = 0
    for hold in list(self._holds.values()):
        if hold.resource_id != resource_id or not self._is_active(hold, now):
            continue
        ...

# confirm_hold's expiry branch:
if datetime.now(UTC) >= hold.expires_at:
    del self._holds[hold_id]  # purge — it can never be confirmed again
    raise HoldExpiredError(hold_id)
```
Add a regression test (e.g. with `time-machine`, already in the recommended stack) that places a
hold with a short TTL, advances time past expiry, and asserts the slot is `AVAILABLE` again and a
new hold can be placed on it without calling `release_hold`.

### CR-02: `grid_slots` infinite-loops when `slot_duration <= 0` or buffer makes the step non-positive

**File:** `src/availability_engine/core/grid.py:19-27`; root cause: `src/availability_engine/contracts.py:64-68`

**Issue:** `Resource.slot_duration` (contracts.py:68) has no constraint requiring it to be
positive, and `Resource.buffer` (contracts.py:66) has no constraint requiring it to be `>= 0` (or
`> -slot_duration`). `grid_slots`'s loop:
```python
step = slot_duration + buffer
while True:
    slot_end = cursor + slot_duration
    if slot_end > fragment.end:
        break
    slots.append(Interval(start=cursor, end=slot_end))
    cursor = cursor + step
```
only terminates because `cursor` is expected to strictly advance past `fragment.end` eventually.
If `slot_duration == timedelta(0)` and `buffer == timedelta(0)` (both currently legal
`Resource` values per the Pydantic schema), `step == timedelta(0)`: `slot_end` never moves past
`fragment.end`, `cursor` never advances, and the loop never terminates — a full hang of the
calling coroutine (and, since `AvailabilityEngine` never spawns this off the event loop, of the
whole process) on every `get_availability` call for that resource. The same hang occurs for any
`slot_duration <= 0`, or for a `buffer` negative enough that `slot_duration + buffer <= 0` while
`slot_duration > 0` still lets slots overlap indefinitely without ever exceeding `fragment.end`
(e.g. `slot_duration=30m, buffer=-30m` → `step=0`).

Nothing else in the codebase validates these fields (confirmed no other `slot_duration`/`buffer`
constraint exists anywhere in `src/`). This is reachable directly from public, untrusted-ish input
— any consumer constructing a `Resource` (the public contract type) with a zero/negative
`slot_duration` or an aggressively negative `buffer` triggers a denial-of-service hang.

**Fix:** Add Pydantic constraints on the public contract type, which is the correct trust
boundary for this check:
```python
slot_duration: Annotated[timedelta, Field(gt=timedelta(0))]  # GRID-01
buffer: Annotated[timedelta, Field(ge=timedelta(0))] = Field(default=timedelta(0))  # MODEL-03
```
This alone prevents `step <= 0` (a positive `slot_duration` plus a non-negative `buffer` can never
sum to `<= 0`). Add a unit test asserting `Resource(..., slot_duration=timedelta(0))` and
`Resource(..., buffer=timedelta(minutes=-60))` both raise `pydantic.ValidationError`.

## Warnings

### WR-01: No validation that `slot_start < slot_end` on hold placement

**File:** `src/availability_engine/engine.py:70-83` (`place_hold`), `src/availability_engine/core/intervals.py:13-18` (`Interval`)

**Issue:** `Interval` is documented as "callers are responsible for passing already-UTC-aware
datetime values" and does no ordering validation of its own (by design, per its docstring), but
nothing upstream of it validates ordering either. `AvailabilityEngine.place_hold` builds
`Interval(start=slot_start, end=slot_end)` directly from caller-supplied `UtcDatetime` values with
no check that `slot_start < slot_end`. A caller passing `slot_end <= slot_start` produces a
zero-length or inverted-duration `Hold`/`Booking` that is stored and returned as if valid — this
silently corrupts booking data (a "booking" with negative or zero duration) rather than being
rejected at the boundary where the mistake is easiest to diagnose.

**Fix:** Validate ordering in `place_hold` before constructing the `Interval`:
```python
if slot_end <= slot_start:
    raise ValueError(f"slot_end ({slot_end}) must be after slot_start ({slot_start})")
```
(or equivalently as a Pydantic `model_validator` on `Hold`/`Booking` themselves, which would also
catch it for any future direct-construction call site).

### WR-02: Inconsistent unknown-resource handling between read and write paths, using a generic `ValueError`

**File:** `src/availability_engine/engine.py:33-38` (`get_availability`), `:77-79` (`place_hold`)

**Issue:** `get_availability` silently returns an empty `AvailabilityResult` when `resource_id` is
unknown (line 37-38: `if resource is None: return AvailabilityResult(resource_id=resource_id,
slots=[])`), while `place_hold` raises a bare `ValueError` for the identical condition (line
78-79). Two different failure modes for "this resource doesn't exist" on the same facade makes it
easy for a consumer to write code that silently no-ops on a typo'd `resource_id` in one call and
crashes on it in another. The bare `ValueError` also breaks the pattern established by
`errors.py`, where every other domain failure (`CapacityExhaustedError`, `HoldExpiredError`,
`HoldNotFoundError`) is a dedicated exception type a consumer can catch specifically — a caller
cannot distinguish "resource not found" from any other `ValueError` a future change might raise.

**Fix:** Add a `ResourceNotFoundError` to `errors.py` following the existing pattern (identifier
only, no payload), raise it from `place_hold`, and decide deliberately whether `get_availability`
should raise the same error or keep returning empty (either is defensible, but they should match).

### WR-03: `place_hold`'s capacity snapshot is fetched outside the storage lock

**File:** `src/availability_engine/engine.py:70-83`

**Issue:** `AvailabilityEngine.place_hold` calls `self._storage.get_resource(resource_id)` to read
`resource.capacity`, then separately calls `self._storage.place_hold(..., resource.capacity, ...)`.
Between those two calls, another coroutine can call `define_resource` (which the same facade
exposes, with no restriction on when it may be called) to change that resource's `capacity`. The
in-memory backend's lock only protects the read-count-vs-capacity comparison against a stale
`capacity` value it wasn't given control over — a hold can be placed using a capacity number that
is already out of date at the moment the lock is acquired, letting more holds through post-facto
capacity reductions than intended. This is a narrow window (requires concurrent resource
redefinition) but is a real gap in the "atomic hold placement" guarantee as currently composed
across the facade/storage boundary.

**Fix:** Either (a) have `StorageBackend.place_hold` re-read the authoritative capacity from its
own store under the same lock instead of accepting it as a caller-supplied parameter, or (b)
document explicitly that `define_resource` must not be called concurrently with in-flight
`place_hold` calls for the same resource if this guarantee matters to a given deployment.

## Info

### IN-01: `CapacityExhaustedError.slot` typed as `Any` weakens the strict-typing convention

**File:** `src/availability_engine/errors.py:16`

**Issue:** `def __init__(self, resource_id: str, slot: Any) -> None` uses `Any` for a parameter
that is always an `Interval` in practice (see `storage/memory.py:83`). The project pins
`mypy --strict` specifically to keep the public contract's type signatures trustworthy; `Any`
here is an unnecessary hole in an otherwise fully-typed exception module.

**Fix:** `def __init__(self, resource_id: str, slot: Interval) -> None` (import `Interval` from
`core.intervals`; no circularity issue since `errors.py` doesn't currently import from `core`).

### IN-02: `free_fragments` docstring claims sweep-line counting, implementation recomputes brute-force per segment

**File:** `src/availability_engine/core/availability.py:14-59`

**Issue:** The docstring and module comment describe an incremental "sweep-line event-counting"
algorithm ("sweep chronologically tracking `active_count`"), but the implementation builds
`events` only to harvest boundary timestamps (line 43-45) and then, for every emitted segment,
recomputes `active_count` from scratch by re-scanning the entire `busy` list (lines 52-55) rather
than incrementally applying the `+1`/`-1` deltas already computed. Functionally correct, but the
docstring misdescribes the algorithm, which will mislead the next person reading it as
documentation of *how* it works (performance is out of review scope, but the doc/code mismatch
itself is a maintainability issue).

**Fix:** Either implement the incremental running-counter version the docstring describes, or
update the docstring to describe what's actually implemented ("boundary points are harvested via
event timestamps; the count for each resulting segment is then computed directly against `busy`").

### IN-03: `InMemoryStore` is not re-exported from `storage/__init__.py`

**File:** `src/availability_engine/storage/__init__.py` (empty)

**Issue:** The top-level package `__init__.py` exports the `StorageBackend` Protocol but the
reference in-memory implementation is only reachable via the more specific
`availability_engine.storage.memory` import path (used throughout the tests). This is a minor
discoverability gap for consumers looking for the shipped reference/test backend — not a
functional bug, since the direct import path works fine.

**Fix:** Consider `from availability_engine.storage.memory import InMemoryStore` +
`__all__ = ["InMemoryStore"]` in `storage/__init__.py` if `InMemoryStore` is meant to be
consumer-facing (e.g. for tests/prototyping in consumer projects), or leave as-is with a one-line
docstring note if it's intentionally kept as a test-only reference implementation.

---

_Reviewed: 2026-09-03T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
