---
phase: 04-sql-backend-concurrency-proof
plan: 04
subsystem: database
tags: [postgres, testcontainers, pytest-asyncio, concurrency, advisory-lock, sqlalchemy]

# Dependency graph
requires:
  - phase: 04-sql-backend-concurrency-proof (Plan 04-01)
    provides: SQLStore's dialect-branch-point locking architecture
      (pg_advisory_xact_lock on Postgres, BEGIN IMMEDIATE on SQLite) — the
      exact mechanism this plan empirically proves under real concurrency
  - phase: 04-sql-backend-concurrency-proof (Plan 04-02)
    provides: testcontainers-Postgres wiring pattern (session-scoped
      container/engine, loop_scope="session") this plan's own dedicated
      fixtures follow, without reusing the shared conftest.py instances
provides:
  - Empirical, real-Postgres proof of HOLD-02 (no overbooking under N
    genuinely concurrent, independently-connected OS-level place_hold
    callers) — two hardened cases (K=1/N=25, K=3/N=30), both asserting exact
    success counts, run reliably across multiple executions
  - Full project-wide green gate closing out Phase 4: 110 tests passing,
    mypy --strict clean, ruff clean except 6 pre-existing/logged violations,
    and a verified empty diff on engine.py/contracts.py across the whole
    phase (Success Criterion #2)
affects: [packaging]

# Actuals (#2632)
actuals:
  tokens: 2424
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns: [
    "The concurrency proof owns its own session-scoped testcontainers
     Postgres container and AsyncEngine (pool_size sized above N), never
     reusing tests/storage/conftest.py's pg_container/pg_engine or
     contract_suite.py's table-delete isolation — binding all activity to
     one shared connection/transaction would be the opposite of the
     genuinely-concurrent-OS-connections requirement HOLD-02 exists to
     prove (RESEARCH.md Pattern 3)",
    "Concurrency assertions use exact success counts (== capacity, not
     <= capacity) plus exception-type assertions on every rejection —
     proves the lock neither over- nor under-serializes"
  ]

key-files:
  created:
    - tests/storage/test_concurrency_proof.py
  modified:
    - .planning/phases/04-sql-backend-concurrency-proof/deferred-items.md

key-decisions:
  - "Sized the dedicated concurrency-proof AsyncEngine's pool at N_max + 10
     (40) with max_overflow=0, so every one of the 30 concurrent tasks in
     the larger case gets its own real, independently-checked-out
     connection — an undersized pool would silently serialize calls at
     checkout, passing the assertion for the wrong reason (queueing, not
     the advisory lock) and producing a false proof."
  - "Reset holds/bookings/idempotency tables via an autouse per-test
     fixture that deletes rows directly (not a rolled-back savepoint) so
     the K=1/N=25 and K=3/N=30 cases stay isolated from each other without
     reusing the contract suite's isolation mechanism."

patterns-established:
  - "Any future concurrency-proof-style test needing genuinely independent
     OS-level connections must follow this file's shape: its own
     session-scoped container/engine fixtures, pool_size >= N, exact
     (not <=) success-count assertions, and explicit table-delete reset
     between cases — never the contract suite's shared/rollback fixtures."

requirements-completed: [HOLD-02]

coverage:
  - id: D1
    description: "25 genuinely concurrent OS-level Postgres connections
      calling place_hold against one capacity-1 resource/slot result in
      exactly 1 success and 24 CapacityExhaustedError rejections, reliably"
    requirement: HOLD-02
    verification:
      - kind: integration
        ref: "tests/storage/test_concurrency_proof.py#test_concurrent_place_hold_never_exceeds_capacity_k1"
        status: pass
    human_judgment: false
  - id: D2
    description: "30 genuinely concurrent OS-level Postgres connections
      against a capacity-3 resource/slot result in exactly 3 successes,
      hardening the proof against a small-N false pass"
    requirement: HOLD-02
    verification:
      - kind: integration
        ref: "tests/storage/test_concurrency_proof.py#test_concurrent_place_hold_never_exceeds_capacity_k3"
        status: pass
    human_judgment: false
  - id: D3
    description: "Full project-wide regression (all four Phase 4
      requirements and all four ROADMAP success criteria) is green: 110
      tests pass, mypy --strict is clean, ruff check has only 6
      pre-existing/logged violations, and engine.py/contracts.py are
      verified untouched across the whole phase (Success Criterion #2)"
    verification:
      - kind: unit
        ref: "uv run pytest (110 passed)"
        status: pass
      - kind: other
        ref: "uv run mypy --strict src (clean, 16 files)"
        status: pass
      - kind: other
        ref: "git diff d8f246e HEAD -- src/availability_engine/engine.py src/availability_engine/contracts.py (empty)"
        status: pass
    human_judgment: false

duration: 2min
completed: 2026-09-04
status: complete
---

# Phase 4 Plan 4: HOLD-02 Concurrency Proof & Phase-Gate Regression Summary

**Empirically proved no-overbooking under 25 and 30 genuinely concurrent, independently-connected real Postgres callers via a dedicated testcontainers fixture, then closed out Phase 4 with a fully green 110-test project-wide gate.**

## Performance

- **Duration:** ~2 min (commit-to-commit)
- **Started:** 2026-09-04T13:14:01-06:00 (Task 1 commit)
- **Completed:** 2026-09-04T13:15:40-06:00 (Task 2 commit)
- **Tasks:** 2/2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- Created `tests/storage/test_concurrency_proof.py` with its own dedicated
  session-scoped testcontainers Postgres container and `AsyncEngine`
  (`pool_size=40, max_overflow=0`), deliberately not sharing
  `tests/storage/conftest.py`'s `pg_container`/`pg_engine` or
  `contract_suite.py`'s table-delete isolation fixture — a genuinely
  independent-connections proof, per RESEARCH.md Pattern 3.
- `test_concurrent_place_hold_never_exceeds_capacity_k1`: 25 concurrent
  `place_hold` calls (`asyncio.gather(..., return_exceptions=True)`) against
  one capacity-1 resource/slot — exactly 1 success, 24
  `CapacityExhaustedError` rejections, every time.
- `test_concurrent_place_hold_never_exceeds_capacity_k3`: 30 concurrent
  calls against a capacity-3 resource/slot — exactly 3 successes, 27
  rejections. Hardens the proof against RESEARCH.md's documented warning
  that a small N against a fast local Postgres may never trigger the race
  even when the underlying code is wrong.
- Both cases re-run reliably 4 times total (1 during authoring, 3 explicit
  repeat runs) — never a "usually passes" result.
- Full Phase 4 gate: `uv run pytest` — 110 passed; `uv run mypy --strict
  src` — clean; `uv run ruff check` — only the 6 pre-existing, already-logged
  violations from Plans 04-01/04-02 remain; `git diff` against the
  phase-3-completion commit confirms `engine.py`/`contracts.py` were never
  touched anywhere in Phase 4 (Success Criterion #2).

## Task Commits

Each task was committed atomically:

1. **Task 1: Prove no-overbooking under N genuinely concurrent OS-level
   Postgres connections** - `a5f30a5` (test)
2. **Task 2: Full-suite phase-gate regression** - `968993c` (test)

## Files Created/Modified
- `tests/storage/test_concurrency_proof.py` - the HOLD-02 empirical proof:
  its own session-scoped Postgres container/engine fixtures, an autouse
  table-reset fixture, and two hardened concurrency cases (K=1/N=25,
  K=3/N=30) with exact success-count and exception-type assertions.
- `.planning/phases/04-sql-backend-concurrency-proof/deferred-items.md` -
  logged the Task 2 re-confirmation of the 6 pre-existing `ruff` E501
  violations and the full-suite/mypy/engine-diff gate results.

## Decisions Made
See `key-decisions` in frontmatter — the pool-sizing rationale (`N_max + 10`
so no task ever queues at connection checkout, which would produce a false
proof) and the explicit table-delete reset strategy between the two
concurrency cases are the two decisions with real weight this plan made.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Two E501 line-length violations in this plan's own new
test file**
- **Found during:** Task 2 (`uv run ruff check`, whole repo)
- **Issue:** Two `store.place_hold(resource.id, slot, capacity=resource.capacity, ttl_seconds=60)`
  call lines inside the `asyncio.gather(...)` generator expressions (one per
  concurrency case) were 91 characters, exceeding the project's 88-character
  line limit — introduced by this plan's own new file, not a pre-existing
  issue.
- **Fix:** Wrapped each call's arguments onto their own indented lines.
- **Files modified:** `tests/storage/test_concurrency_proof.py`
- **Verification:** `uv run ruff check tests/storage/test_concurrency_proof.py`
  — clean. Re-ran `uv run pytest tests/storage/test_concurrency_proof.py -x`
  after the fix — both cases still pass.
- **Committed in:** `968993c` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — a lint violation caused by this
plan's own new file, fixed inline before the Task 2 commit). No scope creep
— the 6 pre-existing violations elsewhere in the repo were left untouched
and re-logged, per the SCOPE BOUNDARY rule.

## Issues Encountered
None beyond the deviation documented above.

## User Setup Required
None - no external service configuration required. `docker info` confirmed
reachable (Task 1's `<precondition>`); testcontainers handled the dedicated
Postgres 17 container lifecycle end-to-end, independent of
`tests/storage/conftest.py`'s own container instance.

## Next Phase Readiness
- All four Phase 4 requirements (STORE-03, STORE-04, STORE-05, HOLD-02) and
  all four ROADMAP success criteria are satisfied and verified by this
  plan's full project-wide green test run.
- HOLD-02's empirical proof confirms the `pg_advisory_xact_lock` fix
  (superseding CONTEXT.md's D-01) is what makes `place_hold` safe under
  genuine concurrent Postgres load — Phase 4 is ready to close.
- The 6 pre-existing `ruff` E501 violations logged across 04-01/04-02/04-04
  remain unresolved; a future cleanup task should address them (unrelated
  to this phase's scope).
- `alembic/` migrations (STORE-05) landed in an earlier plan in this phase;
  wheel packaging of them remains deferred to Phase 5 per CONTEXT.md.

## Self-Check: PASSED

- FOUND: `tests/storage/test_concurrency_proof.py`
- FOUND: `a5f30a5` (Task 1 commit)
- FOUND: `968993c` (Task 2 commit)

---
*Phase: 04-sql-backend-concurrency-proof*
*Completed: 2026-09-04*
