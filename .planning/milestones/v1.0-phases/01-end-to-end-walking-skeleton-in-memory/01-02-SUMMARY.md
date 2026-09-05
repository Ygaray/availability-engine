---
phase: 01-end-to-end-walking-skeleton-in-memory
plan: 02
subsystem: testing
tags: [pydantic, dataclasses, pytest, validation, intervals]

requires:
  - phase: 01-end-to-end-walking-skeleton-in-memory (plan 01)
    provides: "src/availability_engine/contracts.py, core/intervals.py, core/grid.py — the tracer's frozen contract and grid math this plan proves the boundary/negative-path behavior of"
provides:
  - "tests/test_contracts.py — boundary-rejection tests: Resource capacity<1, non-IANA timezone, operating_hours shape round-trip; UtcDatetime rejects naive/non-UTC/date-only-string input"
  - "tests/core/test_intervals.py — Interval frozen-mutation and half-open-boundary proof"
  - "tests/core/test_grid.py — grid_slots() exact slot count and exact inter-slot buffer gap proof"
affects: [02-timezone-dst-and-capacity-hardening]

actuals:
  tokens: 1306
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Boundary-rejection tests use a `_base_*_kwargs()` helper mutated per-test, keeping each `pytest.raises` assertion isolated to the single field under test"

key-files:
  created:
    - tests/test_contracts.py
    - tests/core/__init__.py
    - tests/core/test_intervals.py
    - tests/core/test_grid.py
  modified: []

key-decisions:
  - "No production code changes were needed — Plan 01-01's contracts.py, core/intervals.py, and core/grid.py already satisfied every negative-path/correctness assertion this plan specified; this plan is purely additive test coverage."

patterns-established:
  - "Boundary-rejection test helper pattern: a `_base_*_kwargs()` factory returning a minimal valid kwargs dict, overridden per-test for the single field under test, keeps each ValidationError assertion unambiguous about what triggered it."

requirements-completed: [MODEL-01, MODEL-02, MODEL-03, MODEL-04, MODEL-05, GRID-01, GRID-04]

coverage:
  - id: D1
    description: "Resource rejects capacity < 1 and a non-IANA timezone string; accepts and round-trips a per-weekday list-of-half-open-intervals operating_hours shape"
    requirement: "MODEL-01, MODEL-02, MODEL-04"
    verification:
      - kind: unit
        ref: "tests/test_contracts.py#test_resource_capacity_ge_1"
        status: pass
      - kind: unit
        ref: "tests/test_contracts.py#test_resource_operating_hours_shape"
        status: pass
      - kind: unit
        ref: "tests/test_contracts.py#test_resource_timezone_validation"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every UtcDatetime boundary field rejects a naive datetime, a non-UTC aware datetime, and a bare date-only string"
    requirement: "GRID-04"
    verification:
      - kind: unit
        ref: "tests/test_contracts.py#test_naive_datetime_rejected"
        status: pass
    human_judgment: false
  - id: D3
    description: "core.intervals.Interval is frozen (mutation raises FrozenInstanceError) and half-open (a point equal to .end is not contained/overlapping)"
    requirement: "MODEL-05"
    verification:
      - kind: unit
        ref: "tests/core/test_intervals.py#test_frozen_and_half_open"
        status: pass
    human_judgment: false
  - id: D4
    description: "grid_slots() produces exactly the expected slot count for a known fragment/slot_duration pair, and leaves exactly `buffer` between consecutive slots"
    requirement: "GRID-01, MODEL-03"
    verification:
      - kind: unit
        ref: "tests/core/test_grid.py#test_grid_slots_basic"
        status: pass
      - kind: unit
        ref: "tests/core/test_grid.py#test_buffer_applied"
        status: pass
    human_judgment: false

duration: ~12min
completed: 2026-09-03
status: complete
---

# Phase 1 Plan 2: Validation-Depth Test Layer Summary

**Seven new passing unit tests proving contracts.py's boundary rejections (capacity, IANA timezone, UTC-only datetimes) and core.intervals/core.grid's frozen half-open Interval and buffer-aware grid_slots() semantics — zero production code changes.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-09-03T21:19:00Z
- **Tasks:** 2
- **Files modified:** 4 (all new)

## Accomplishments

- `tests/test_contracts.py`: four tests proving `Resource` rejects `capacity=0` and `timezone="Not/AZone"`, accepts and round-trips a two-`LocalInterval`-per-weekday shape, and proving `Hold.expires_at` (a `UtcDatetime` field) rejects a naive datetime, a non-UTC `+05:00`-offset aware datetime, and a bare `"2026-09-03"` date-only string
- `tests/core/test_intervals.py`: proves `Interval` raises `dataclasses.FrozenInstanceError` on attribute assignment, and that `overlaps()` returns `False` for two intervals sharing only a boundary point (half-open semantics, MODEL-05)
- `tests/core/test_grid.py`: proves `grid_slots()` produces exactly 2 contiguous 30-min slots for a 1-hour fragment with zero buffer, and exactly 2 slots (not 3) with a 10-min inter-slot gap when `slot_duration=20min, buffer=10min`
- No changes to `src/` — every assertion this plan specified was already satisfied by Plan 01-01's implementation

## Task Commits

Each task was committed atomically:

1. **Task 1: Boundary-rejection tests for Resource and UtcDatetime** - `ef9e2f0` (test)
2. **Task 2: Interval half-open/frozen tests and grid_slots buffer-application tests** - `08a9264` (test)

_Note: This plan is a pure test-addition plan (`tdd="true"` on tests proving existing behavior) — no separate feat/refactor commits were needed since no production code required changes._

## Files Created/Modified

- `tests/test_contracts.py` - Boundary-rejection tests for `Resource` (capacity, operating_hours shape, timezone) and `UtcDatetime` (naive/non-UTC/date-only-string rejection)
- `tests/core/__init__.py` - Empty package marker for `tests/core/`
- `tests/core/test_intervals.py` - `Interval` frozen-mutation and half-open-boundary tests
- `tests/core/test_grid.py` - `grid_slots()` basic slot-count and buffer-application tests

## Decisions Made

- No production code changes were needed anywhere in this plan — Plan 01-01's `contracts.py`, `core/intervals.py`, and `core/grid.py` already satisfied every negative-path/correctness assertion specified. This plan is purely additive test coverage, exactly as scoped ("tests only, no production code changes").

## Deviations from Plan

None - plan executed exactly as written. One minor style fix (using `datetime.UTC` alias instead of `timezone.utc` to satisfy the repo's `ruff` `UP017` rule already enforced on `src/`) was applied inline while authoring `tests/test_contracts.py`, before the file was ever committed — not a deviation from a committed state, just normal lint-clean authoring.

## Issues Encountered

None. All four Task 1 tests and all three Task 2 tests passed on first run against Plan 01-01's existing implementation; the full test suite (9 tests: 2 from Plan 01-01 + 7 new) passes with no regressions.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MODEL-01/02/03/04/05 and GRID-01/GRID-04 are now proven by passing automated tests, not just implicitly exercised by the Plan 01-01 tracer's one happy-path scenario — closing the validation-depth gap this plan targeted.
- `tests/core/` package now exists as the home for future `core.*` module unit tests (e.g., Phase 2's DST/midnight-crossing fixtures can live alongside `test_intervals.py`/`test_grid.py`).
- No blockers for Phase 2 (timezone/DST + capacity-K hardening) or the sibling Plan 01-03.

---
*Phase: 01-end-to-end-walking-skeleton-in-memory*
*Completed: 2026-09-03*

## Self-Check: PASSED

All 4 claimed key-files verified present on disk. Both task commits (`ef9e2f0`, `08a9264`) verified present in `git log`.
