---
phase: 02-capacity-time-correctness
plan: 01
subsystem: scheduling-engine
tags: [zoneinfo, dst, timezone, pytest, tzdata, time-machine, hypothesis, uv]

# Dependency graph
requires:
  - phase: 01-end-to-end-walking-skeleton-in-memory
    provides: "Resource/LocalInterval contract types, time.py::localize_operating_hours, core/grid.py grid stepper"
provides:
  - "Fixed localize_operating_hours midnight-crossing date arithmetic (GRID-03)"
  - "Fixture-proven DST-transition correctness on real 2026 America/New_York dates (GRID-02)"
  - "tzdata, time-machine, hypothesis pinned in pyproject.toml for the whole phase"
  - "_is_imaginary/_is_ambiguous test-local detection helpers for gap/ambiguous boundaries"
affects: [02-02, 02-03, capacity-shape, contract-conformance]

# Actuals (#2632)
actuals:
  tokens: 3040
  tasks: 3
  commits: 5

# Tech tracking
tech-stack:
  added: [tzdata==2026.3, time-machine==3.5.0, hypothesis==6.167.1]
  patterns:
    - "DST correctness lives entirely in the one-time UTC boundary conversion (time.py), never in the grid stepper (core/grid.py) — verified zero-diff on grid.py"
    - "Midnight-crossing sentinel (end <= start) anchors the end boundary on current_date + 1 day, never +2"
    - "Imaginary/ambiguous local-time detection via round-trip (_is_imaginary) and fold comparison (_is_ambiguous), not construction-time exceptions (Python's zoneinfo never raises on a gap/ambiguous time per PEP 495)"

key-files:
  created:
    - tests/test_time_boundary.py
    - tests/core/test_grid_dst.py
  modified:
    - pyproject.toml
    - src/availability_engine/time.py

key-decisions:
  - "Task 1 followed as a genuine tracer (TDD RED/GREEN, then verified end-to-end) before expanding to Tasks 2-3 — the tracer feedback gate confirmed a passing full suite (23/23) and zero core/grid.py diff before further work landed."
  - "Deviation (Rule 1 — auto-fix bug): the plan's Task 3 gap-boundary fixture test asserted a 90-minute UTC span for LocalInterval(2:30->4:00) on 2026-03-08; direct zoneinfo execution proved the correct value is 30 minutes (fold=0 resolves the nonexistent 02:30 to the pre-transition EST offset, equivalent to real 03:30 EDT, giving a 30-minute span to 04:00 EDT). Implemented and asserted the verified-correct 30-minute value instead of the plan's stated 90-minute figure."

patterns-established:
  - "Fixture tests hardcode real, dated IANA transition instants (2026-03-08, 2026-11-01) rather than relative 'next DST date' computation, per RESEARCH.md's verified-by-execution approach."

requirements-completed: [GRID-02, GRID-03]

coverage:
  - id: D1
    description: "Fixed the midnight-crossing date-arithmetic bug in localize_operating_hours: an overnight LocalInterval (end <= start) now anchors its end boundary on the following calendar day instead of the same day, producing a correct 8-hour UTC span instead of an inverted/zero-length interval."
    requirement: "GRID-03"
    verification:
      - kind: unit
        ref: "tests/test_time_boundary.py#test_overnight_interval_spans_into_next_calendar_day"
        status: pass
    human_judgment: false
  - id: D2
    description: "Proved DST-transition correctness (spring-forward gap, fall-back doubled hour) is already handled correctly by the existing UTC-boundary-conversion design, with zero DST-aware code needed in the grid stepper — fixture-tested against real 2026 America/New_York transition dates for both an overnight-crossing window and a midnight-boundary-only window."
    requirement: "GRID-02"
    verification:
      - kind: unit
        ref: "tests/core/test_grid_dst.py#test_overnight_window_spring_forward_yields_7_hours"
        status: pass
      - kind: unit
        ref: "tests/core/test_grid_dst.py#test_overnight_window_fall_back_yields_9_hours"
        status: pass
      - kind: unit
        ref: "tests/core/test_grid_dst.py#test_midnight_boundary_only_spring_forward_yields_3_hours"
        status: pass
      - kind: unit
        ref: "tests/core/test_grid_dst.py#test_midnight_boundary_only_fall_back_yields_5_hours"
        status: pass
    human_judgment: false
  - id: D3
    description: "Documented and fixture-tested Python's deterministic fold=0 default behavior for a LocalInterval boundary landing inside a DST gap (collapses forward) or a doubled hour (resolves to the earlier occurrence), including reusable _is_imaginary/_is_ambiguous detection helpers, per D-01's 'skip the non-existent spring-forward hour' contract."
    requirement: "GRID-03"
    verification:
      - kind: unit
        ref: "tests/test_time_boundary.py#test_is_imaginary_detects_spring_forward_gap"
        status: pass
      - kind: unit
        ref: "tests/test_time_boundary.py#test_is_ambiguous_detects_fall_back_doubled_hour"
        status: pass
      - kind: unit
        ref: "tests/test_time_boundary.py#test_boundary_inside_spring_forward_gap_collapses_forward_30_minutes"
        status: pass
      - kind: unit
        ref: "tests/test_time_boundary.py#test_boundary_inside_fall_back_doubled_hour_resolves_to_earlier_occurrence"
        status: pass
    human_judgment: false
  - id: D4
    description: "Pinned tzdata, time-machine, and hypothesis in pyproject.toml — the one dependency touch-point for the whole phase, so Wave 2's 02-02/02-03 plans never need to edit pyproject.toml themselves."
    verification:
      - kind: unit
        ref: "pyproject.toml [project].dependencies / [dependency-groups].dev entries; uv run pytest tests/ -x -q"
        status: pass
    human_judgment: false

# Metrics
duration: ~20min
completed: 2026-09-03
status: complete
---

# Phase 2 Plan 1: Midnight-Crossing Fix + DST Fixture Proof Summary

**Fixed the one verified `time.py::localize_operating_hours` midnight-crossing bug and fixture-proved the existing UTC-boundary-conversion design is already DST-correct by construction on real 2026 America/New_York transition dates, with zero changes to `core/grid.py`.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3 completed
- **Files modified:** 5 (pyproject.toml, uv.lock, src/availability_engine/time.py, tests/test_time_boundary.py, tests/core/test_grid_dst.py)

## Accomplishments
- Fixed the real, verified GRID-03 bug: `localize_operating_hours` now anchors an overnight `LocalInterval`'s end boundary on `current_date + 1` when `end <= start`, instead of unconditionally using the start day — proven via a TDD RED/GREEN cycle (test failed against the inverted interval before the fix, passed after).
- Fixture-proved GRID-02 (DST-transition correctness) on real 2026 `America/New_York` spring-forward (2026-03-08) and fall-back (2026-11-01) dates: overnight 22:00→06:00 windows yield 7h/9h; midnight-boundary-only 00:00→04:00 windows yield 3h/5h — exactly matching RESEARCH.md's pre-verified table, with `core/grid.py` untouched (zero diff).
- Documented and fixture-tested the `fold=0` default behavior for a `LocalInterval` boundary landing inside a DST gap or doubled hour, including `_is_imaginary`/`_is_ambiguous` test-local detection helpers.
- Pinned all three Phase-2 dependencies (`tzdata==2026.3`, `time-machine==3.5.0`, `hypothesis==6.167.1`) in one `pyproject.toml` commit, freeing Wave 2's plans from touching that file.

## Task Commits

Each task was committed atomically (Task 1 followed TDD RED/GREEN, split across 3 commits; dependency pinning is its own setup commit):

1. **Dependency pinning (Task 1 setup)** - `e968271` (chore)
2. **Task 1: Midnight-crossing fix — RED** - `eff0b07` (test)
3. **Task 1: Midnight-crossing fix — GREEN** - `801d712` (feat)
4. **Task 2: DST-transition fixture tests (GRID-02)** - `e588df7` (test)
5. **Task 3: Imaginary/ambiguous boundary detection + fixture tests** - `5b9132a` (test)

_Note: Task 1 was `tdd="true"` and `type="tracer"` — RED/GREEN split into separate commits per the TDD execution protocol, with a tracer feedback gate (full-suite re-verification) run before expanding into Tasks 2-3._

## Files Created/Modified
- `pyproject.toml` - Pinned `tzdata`, `time-machine`, `hypothesis`
- `src/availability_engine/time.py` - Fixed `localize_operating_hours` midnight-crossing date arithmetic; updated module docstring to document the fix and DST-correctness-by-construction
- `tests/test_time_boundary.py` (new) - Overnight midnight-crossing fixture test, `_is_imaginary`/`_is_ambiguous` helpers, gap-boundary and ambiguous-boundary fixture tests
- `tests/core/test_grid_dst.py` (new) - 4 DST-transition fixture tests on real 2026 `America/New_York` transition dates

## Decisions Made
- Followed the plan's TDD structure for Task 1 (RED commit, then GREEN commit) even though the phase-wide `tdd_mode` config flag is `false` — the individual task's `tdd="true"` frontmatter attribute governs per-task execution, not the global config toggle.
- Split dependency pinning into its own `chore` commit ahead of the RED test commit, since it's setup infrastructure rather than either the test or the fix itself — keeps each commit's diff focused on one concern.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the plan's incorrect 90-minute expected value for the spring-forward gap-boundary fixture test**
- **Found during:** Task 3 (imaginary/ambiguous boundary detection tests)
- **Issue:** The plan's Task 3 action/acceptance-criteria specified `LocalInterval(start=time(2,30), end=time(4,0))` on `2026-03-08` (spring-forward) should yield "exactly a 90-minute UTC fragment." Direct execution against `zoneinfo` (not just the plan's stated arithmetic) showed the actual, correct span is 30 minutes: `fold=0`'s default interpretation of the nonexistent `02:30` uses the pre-transition EST (UTC-5) offset, giving `07:30 UTC` — the same instant as the valid `03:30 EDT` immediately after the gap — while `local_end` (`04:00`, unambiguous EDT) converts to `08:00 UTC`, an elapsed span of 30 minutes, not 90.
- **Fix:** Implemented the test asserting the verified-correct 30-minute span, with an in-code comment explaining the offset arithmetic, rather than asserting the plan's incorrect 90-minute figure.
- **Files modified:** `tests/test_time_boundary.py`
- **Verification:** Directly executed `zoneinfo` conversion via `python3` to confirm `07:30:00+00:00` / `08:00:00+00:00` before writing the assertion; test passes.
- **Committed in:** `5b9132a` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix to a plan-specified test expectation)
**Impact on plan:** The underlying production behavior (fold=0 default, D-01's contract) is unchanged and correctly implemented — only the plan's own stated numeric expectation for one test assertion was wrong. No scope creep; the fix keeps the test suite internally consistent and factually correct.

## Issues Encountered
None beyond the deviation documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `time.py::localize_operating_hours` is now correct for midnight-crossing and DST transitions, fixture-proven on real dates — Wave 2's 02-02 (capacity-shape) and 02-03 (reason codes / lazy expiry) plans can build on this without revisiting time-boundary logic.
- `tzdata`, `time-machine`, `hypothesis` are pinned and available — Wave 2 plans should not re-touch `pyproject.toml`'s dependency lists.
- `core/grid.py` remains untouched, confirming the phase's architectural guardrail (DST correctness confined to `time.py`) held throughout this plan.
- No blockers for Wave 2.

---
*Phase: 02-capacity-time-correctness*
*Completed: 2026-09-03*
