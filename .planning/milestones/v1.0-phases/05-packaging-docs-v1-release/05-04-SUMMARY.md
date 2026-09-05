---
phase: 05-packaging-docs-v1-release
plan: 04
subsystem: docs
tags: [readme, doc-examples, pytest, regression-guard]

# Dependency graph
requires:
  - phase: 05-packaging-docs-v1-release
    plan: "05-01"
    provides: "get_script_location() -- the packaged Alembic script_location resolver README.md cites in its storage-protocol section"
  - phase: 05-packaging-docs-v1-release
    plan: "05-02"
    provides: "SyncAvailabilityEngine -- the sync facade README.md documents alongside the async AvailabilityEngine"
provides:
  - "README.md -- the stable, documented public product surface (PKG-02): both engine facades, storage protocol, output contract, concurrency guarantees, TZ/DST semantics"
  - "tests/test_readme_examples.py -- CI-enforced regression guard proving README's core call sequence runs against the real installed API (both facades)"
affects: [05-05, release]

# Actuals (#2632)
actuals:
  tokens: 3559
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Doc-example regression test: mirror the README's exact code example verbatim in a real (non-mocked) test, asserting on real return values rather than 'no exception raised' -- so README/API drift fails CI"

key-files:
  created:
    - tests/test_readme_examples.py
  modified:
    - README.md

key-decisions:
  - "Cited concurrency guarantees exactly as Phase 4 proved them (pg_advisory_xact_lock on Postgres, BEGIN IMMEDIATE on SQLite, the K-of-N testcontainers proof) rather than a generic 'thread-safe' claim, per the plan's kept prohibition"
  - "Cited TZ/DST guarantees as fixture-tested on documented 2026 transition dates, not an unconditional guarantee for every timezone/year"
  - "Documented examples/chatbot_adapter.py as a forward reference (created concurrently by sibling wave-2 plan 05-03) -- the README's Example Integration section names it as dev/reference-only, never part of the installed wheel, matching the existing wheel-namelist regression guard's exclusion"

patterns-established:
  - "Every README code example must have a matching real (non-mocked) pytest test asserting on real return values, not just 'no exception raised' -- prevents doc rot silently reaching a consumer"

requirements-completed: [PKG-02]

coverage:
  - id: D1
    description: "README.md documents both engine facades (AvailabilityEngine, SyncAvailabilityEngine), the storage protocol, the output contract, concurrency guarantees, and TZ/DST semantics as the stable product surface"
    requirement: "PKG-02"
    verification:
      - kind: automated
        ref: "grep checks in 05-04-PLAN.md's <verify> block -- SyncAvailabilityEngine, pg_advisory_xact_lock, BEGIN IMMEDIATE, ReasonCode all present"
        status: pass
    human_judgment: false
  - id: D2
    description: "README's concurrency claims cite exactly pg_advisory_xact_lock (Postgres) and BEGIN IMMEDIATE (SQLite), never a broader guarantee"
    requirement: "PKG-02"
    verification:
      - kind: code-review
        ref: "README.md#concurrency-guarantees section names both functions verbatim and states the proven guarantee precisely (at most K of N concurrent place_hold calls succeed on a capacity-K resource)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every README code example is exercised by an automated test against the real installed API"
    requirement: "PKG-02"
    verification:
      - kind: unit
        ref: "tests/test_readme_examples.py::test_readme_async_example_end_to_end, tests/test_readme_examples.py::test_readme_sync_example_end_to_end"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-09-04
status: complete
---

# Phase 5 Plan 4: README.md -- The Stable Product Surface Summary

**Rewrote README.md from a pre-planning scaffold stub into the frozen, documented product surface (PKG-02) -- both engine facades, the storage protocol, the output contract, the exact dialect-aware locking mechanisms Phase 4 proved, and fixture-tested TZ/DST semantics -- with every code example proven to run against the real installed API by a new automated test rather than a manual read-through.**

## Performance

- **Duration:** 25 min
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `README.md` replaced its Phase-0 planning-scaffold content (the original seed brief pointing at `/gsd-new-project`) with the actual, grounded product surface: Install, Engine facade (both `AvailabilityEngine` and `SyncAvailabilityEngine`, one runnable example each), Storage protocol (`StorageBackend`'s 6 methods, `InMemoryStore`/`SQLStore`, `get_script_location()` for Alembic bootstrap), Output contract (`AvailabilityResult`'s two-list shape, `PublicSlot.capacity`/`.remaining` as counts, all 7 typed exceptions with their `.reason_code` in a lookup table), Concurrency guarantees (named exactly: `pg_advisory_xact_lock` via `acquire_postgres_slot_lock`, `BEGIN IMMEDIATE` via `attach_sqlite_begin_immediate`, the K-of-N testcontainers-Postgres proof), TZ/DST semantics (the `UtcDatetime`/`require_utc` boundary, fixture-tested spring-forward/fall-back and midnight-crossing hours), and Example integration (a forward pointer to `examples/chatbot_adapter.py`, dev/reference-only, never shipped in the wheel)
- `tests/test_readme_examples.py` proves both facade examples for real: `test_readme_async_example_end_to_end` drives `AvailabilityEngine` over `InMemoryStore` through `define_resource` -> `get_availability` -> `place_hold` -> `confirm_hold` -> `cancel_booking`, asserting real return values at each step (non-empty `result.available`, a real `hold.id`, `booking.status == BookingStatus.CONFIRMED`, the exact payload roundtrip); `test_readme_sync_example_end_to_end` mirrors the same sequence through `SyncAvailabilityEngine` from a plain synchronous test function, ending in `close()`

## Task Commits

Each task was committed atomically:

1. **Task 1: Write README.md as the stable, documented product surface (PKG-02)** - `442eb48` (docs)
2. **Task 2: Automated doc-example regression test** - `addd975` (test)

## Files Created/Modified

- `README.md` - full rewrite from planning-scaffold stub to the documented product surface (7 sections: Install, Engine facade x2, Storage protocol, Output contract, Concurrency guarantees, TZ/DST semantics, Example integration)
- `tests/test_readme_examples.py` - 2 tests proving README's core call sequence against the real installed API for both facades

## Decisions Made

- Cited the exact proven mechanisms and dates throughout, per the plan's kept prohibition (T-05-07): "at most K of N concurrent `place_hold` calls succeed on a capacity-K resource, proven against real Postgres" rather than a general "atomic"/"thread-safe" claim; DST correctness scoped to "fixture-tested on documented 2026 transition dates," not a universal guarantee
- Documented `examples/chatbot_adapter.py` as a forward reference even though it does not yet exist on disk at this plan's execution time -- it is created concurrently by sibling wave-2 plan `05-03` (both plans depend only on `05-01`/`05-02`, not on each other); the README section is worded as a pointer to reference/dev-only code, matching `tests/packaging/test_wheel_contains_migrations.py`'s existing exclusion guard rather than asserting anything about the file's current presence

## TDD Gate Compliance

Task 2 (`tdd="true"`) was written and passed on the first test run -- no separate RED-phase failure. This is expected, not a fail-fast violation: this plan adds zero new production code. `AvailabilityEngine` and `SyncAvailabilityEngine` were both already fully implemented and tested by Phases 1-4 and by 05-02 respectively; this plan's "new" thing being proven is that README.md's documented call sequence, verbatim, runs correctly against that already-shipped implementation -- a regression-proof commit, matching the same pattern already established and documented in 05-02-SUMMARY.md's Task 2. Committed as a single `test(...)` commit rather than a RED/GREEN pair.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mypy `func-returns-value` findings on two `cancel_booking` call sites**
- **Found during:** Task 2, running `mypy --strict tests/test_readme_examples.py` before committing
- **Issue:** `cancel_booking` returns `None` on both facades; wrapping the call in `assert ... is None` triggered mypy's `func-returns-value` check (asserting on a call that "returns" `None` reads as a no-op assertion)
- **Fix:** Called `cancel_booking(...)` as a bare statement instead of wrapping it in an assertion, on both the async and sync test
- **Files modified:** `tests/test_readme_examples.py`
- **Verification:** `uv run mypy --strict tests/test_readme_examples.py` -- clean; `uv run pytest tests/test_readme_examples.py -x` -- still green
- **Committed in:** `addd975` (Task 2 commit, folded in before the single commit -- no separate fixup commit needed)

---

**Total deviations:** 1 auto-fixed (mypy type-check finding, no behavior change)
**Impact on plan:** Cosmetic only -- no scope creep, no behavior change.

## Issues Encountered

None.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- README.md is now the frozen, documented product surface a consumer (or the parallel `SocialNetwork-Chatbot`) can code against with confidence -- every claim is grounded in what Phases 1-4 actually proved, and every code example is regression-guarded
- `examples/chatbot_adapter.py` (sibling wave-2 plan 05-03) should keep the README's "Example integration" section's framing (dev/reference-only, never shipped in the wheel) intact when it lands -- no README follow-up expected unless the adapter's actual public surface differs materially from the D-03 decision this section already reflects
- Full suite verified green: `uv run pytest` -- 122 passed (120 pre-existing + 2 new), `ruff check` and `mypy --strict` clean on the new test file

---
*Phase: 05-packaging-docs-v1-release*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created/modified files verified present on disk; both task commit hashes (`442eb48`, `addd975`) verified present in git log.
