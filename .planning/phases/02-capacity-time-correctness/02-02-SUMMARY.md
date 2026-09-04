---
phase: 02-capacity-time-correctness
plan: 02
subsystem: storage-backend
tags: [in-memory-store, hold-expiry, ttl, time-machine, tdd]

# Dependency graph
requires:
  - phase: 01-end-to-end-walking-skeleton-in-memory
    provides: "InMemoryStore, AvailabilityEngine.place_hold, confirm_hold's existing expires_at > now predicate"
  - phase: 02-capacity-time-correctness
    plan: 01
    provides: "tzdata/time-machine/hypothesis pinned in pyproject.toml"
provides:
  - "get_active_entries() as the one shared, expiry-filtering active-entries primitive (AVAIL-03)"
  - "Lazy hold expiry: an expired-but-never-released hold no longer occupies capacity (HOLD-05)"
affects: [02-03, phase-4-sql-storage]

# Actuals (#2632)
actuals:
  tokens: 2343
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "get_active_entries() is the ONE shared, expiry-filtering active-entries primitive — every read/write path that needs to know what currently occupies capacity calls it, never a duplicate scan"
    - "Active iff hold.expires_at > now — identical predicate to confirm_hold's existing check, applied consistently"
    - "Lazy release only: an expired Hold record stays in _holds until an explicit release_hold/confirm_hold call; it is simply excluded from active-entries counting"
    - "await get_active_entries(...) inside place_hold's async with self._lock: block is safe — zero real I/O, no suspension point, so it does not reopen the TOCTOU window"

key-files:
  created:
    - tests/test_hold_expiry.py
  modified:
    - src/availability_engine/storage/memory.py
    - tests/storage/contract_suite.py

key-decisions:
  - "Followed the plan's TDD tracer structure exactly: RED test committed first (proved the gap is real — test 2 failed against unfixed InMemoryStore), then GREEN fix committed separately, then the tracer feedback gate (full-suite re-run) confirmed 33/33 green before expanding into Task 2."
  - "No deviations from plan — the fix, test structure, and acceptance criteria all matched RESEARCH.md's verified Pattern 3 exactly."

patterns-established:
  - "Contract-suite tests use time_machine.travel(...) directly (not a custom fixture) to advance past a hold's TTL, matching the style already established by tests/test_hold_expiry.py."

requirements-completed: [AVAIL-03, HOLD-05]

coverage:
  - id: D1
    description: "get_active_entries() now filters holds by hold.expires_at > now, applying the exact predicate confirm_hold already used correctly; _count_active() is deleted entirely and place_hold reuses get_active_entries() as its capacity-check primitive."
    requirement: "AVAIL-03"
    verification:
      - kind: unit
        ref: "tests/test_hold_expiry.py::test_expired_hold_stops_blocking_capacity_with_no_explicit_release"
        status: pass
      - kind: unit
        ref: "tests/storage/contract_suite.py::TestStorageContractSuite::test_get_active_entries_excludes_expired_hold"
        status: pass
    human_judgment: false
  - id: D2
    description: "An expired-but-never-explicitly-released hold no longer occupies capacity forever — a second place_hold on the same capacity-1 slot succeeds once the first hold's TTL elapses, with no release_hold/confirm_hold call and no background sweeper. The expired Hold record itself persists in _holds (lazy release, not deletion)."
    requirement: "HOLD-05"
    verification:
      - kind: unit
        ref: "tests/test_hold_expiry.py::test_expired_hold_stops_blocking_capacity_with_no_explicit_release"
        status: pass
      - kind: unit
        ref: "tests/test_hold_expiry.py::test_active_hold_blocks_second_hold_while_unexpired"
        status: pass
    human_judgment: false
  - id: D3
    description: "get_active_entries() returns an empty list when a resource has zero active holds/bookings in the query window (pre-existing Phase 1 behavior, proven unchanged at the shared-primitive level)."
    requirement: "AVAIL-03"
    verification:
      - kind: unit
        ref: "tests/storage/contract_suite.py::TestStorageContractSuite::test_get_active_entries_empty_when_no_entries"
        status: pass
    human_judgment: false

# Metrics
duration: ~10min
completed: 2026-09-03
status: complete
---

# Phase 2 Plan 2: Lazy Hold-Expiry Fix Summary

**Collapsed `InMemoryStore`'s two duplicated, non-expiry-filtering active-entries scans into one shared `get_active_entries()` primitive that correctly excludes expired holds, fixing the real, verified AVAIL-03/HOLD-05 gap where an unreleased expired hold blocked capacity forever.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2 completed
- **Files modified:** 3 (`src/availability_engine/storage/memory.py`, `tests/test_hold_expiry.py` new, `tests/storage/contract_suite.py`)

## Accomplishments

- Proved the gap was real via TDD RED: `tests/test_hold_expiry.py`'s lazy-expiry test failed against the unfixed `InMemoryStore` (a second `place_hold` on a capacity-1 slot stayed blocked by an expired-but-never-released hold), while the "unexpired hold blocks a second hold" harness test passed — confirming the test setup itself was sound before the fix landed.
- Fixed the gap (GREEN): `get_active_entries()` now filters `self._holds` by `hold.expires_at > now` (the exact predicate `confirm_hold` already used correctly); `_count_active()` is deleted entirely; `place_hold` now calls `await self.get_active_entries(resource_id, slot)` and compares `len(active)` against `effective_capacity` — one shared primitive, per AVAIL-03's literal wording.
- Ran the tracer feedback gate: re-ran `uv run pytest tests/test_hold_expiry.py tests/ -x -q` end-to-end after the GREEN commit — 33/33 passed — before expanding into Task 2.
- Extended `tests/storage/contract_suite.py` (the backend-agnostic `StorageBackend` conformance suite, parametrized over `[InMemoryStore]`, extended by Phase 4's future `SQLStore` for free) with two new tests proving AVAIL-03's expiry-exclusion and empty-input truths at the shared-primitive level, independent of `place_hold`'s capacity check.
- Verified `engine.py` has zero diff (the `StorageBackend` Protocol signature is unchanged — only `InMemoryStore`'s internal behavior was corrected), `_count_active` has zero remaining references anywhere in `src/`, and the full suite (35 tests), `ruff check`, and `mypy --strict` are all clean.

## Task Commits

Each task was committed atomically (Task 1 followed TDD RED/GREEN per its `tdd="true"` frontmatter attribute):

1. **Task 1: Lazy-expiry test — RED** - `cdb6fa8` (test)
2. **Task 1: Shared expiry-filtering primitive — GREEN** - `9b2dd9c` (feat)
3. **Task 2: Contract-suite expiry-exclusion + empty-input tests** - `6fbfd36` (test)

_Note: Task 1 was `tdd="true"` and `type="tracer"` — RED/GREEN split into separate commits per the TDD execution protocol, with the tracer feedback gate (full-suite re-verification) run before expanding into Task 2._

## Files Created/Modified

- `src/availability_engine/storage/memory.py` — `get_active_entries()` gains `hold.expires_at > now` filtering (with an explanatory comment on lazy release and the TOCTOU-safety of awaiting it inside the lock); `_count_active()` deleted; `place_hold` now calls `get_active_entries()` instead of the deleted duplicate.
- `tests/test_hold_expiry.py` (new) — Two end-to-end tests driving `AvailabilityEngine.place_hold` over a fresh `InMemoryStore`: an unexpired hold blocks a second hold (harness-correctness proof); an expired hold (via `time_machine.travel`, no explicit release) stops blocking capacity.
- `tests/storage/contract_suite.py` — Two new tests added to `TestStorageContractSuite`: `test_get_active_entries_excludes_expired_hold` and `test_get_active_entries_empty_when_no_entries`, under the existing `parametrize([InMemoryStore])` decorator.

## Decisions Made

- Followed the plan's TDD tracer structure exactly: wrote and ran the RED test first (confirming test 2 failed against the unfixed store, test 1 passed against the current, correct harness), then implemented the GREEN fix as a separate commit, then re-ran the full suite as the tracer feedback gate before touching Task 2's file.
- No deviations from the plan were needed — RESEARCH.md's Pattern 3 (verified this session by a direct source read) matched the actual codebase exactly, and the plan's acceptance criteria were met without any auto-fix, architectural question, or scope adjustment.

## Deviations from Plan

None. The plan's action, acceptance criteria, and verification steps were followed exactly as written; no Rule 1-4 deviations were needed.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `InMemoryStore.get_active_entries()` is now the single, correct, expiry-filtering active-entries primitive for both `place_hold`'s capacity check and `get_availability`'s busy-interval read — any future Phase 2/3/4 work (including 02-03's reason-code and capacity-shape changes, and Phase 4's `SQLStore`) can rely on this as the canonical behavior.
- The `TestStorageContractSuite` in `tests/storage/contract_suite.py` now enforces expiry-exclusion and empty-input behavior at the backend-agnostic contract level — Phase 4's `SQLStore` addition to the suite's `parametrize` list will automatically be held to the same standard with zero new test-writing.
- `engine.py` and `core/grid.py`/`core/availability.py` remain completely untouched by this plan, confirming the phase's architectural guardrail (this plan's scope was strictly the storage layer) held throughout.
- No blockers for 02-03 or any subsequent plan.

---
*Phase: 02-capacity-time-correctness*
*Completed: 2026-09-03*

## Self-Check: PASSED

All created/modified files verified present (`src/availability_engine/storage/memory.py`, `tests/test_hold_expiry.py`, `tests/storage/contract_suite.py`, this SUMMARY.md). All 4 commits verified in `git log` (`cdb6fa8`, `9b2dd9c`, `6fbfd36`, `33b9990`).
