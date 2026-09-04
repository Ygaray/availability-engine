---
phase: 04-sql-backend-concurrency-proof
plan: 02
subsystem: database
tags: [sqlalchemy, asyncpg, aiosqlite, testcontainers, postgres, pytest-asyncio, storage-backend]

# Dependency graph
requires:
  - phase: 04-sql-backend-concurrency-proof (Plan 04-01)
    provides: SQLStore satisfying StorageBackend against SQLite, the dialect-branch-point
      architecture (locking.py), and the shared contract_suite.py already parametrized
      over InMemoryStore + SQLStore-on-SQLite
provides:
  - Real testcontainers-Postgres fixtures (pg_container/pg_engine) in
    tests/storage/conftest.py, session-scoped alongside the existing sqlite_engine
  - The shared contract_suite.py now runs, byte-for-byte unchanged in every test body,
    against all three backends (in-memory, sqlite, postgres) — 51 passing cases
  - The first genuine execution of locking.py's pg_advisory_xact_lock branch against a
    real Postgres dialect (sequential correctness only — Wave 3's HOLD-02 is the
    concurrency proof)
  - A documented, isolated fix for the asyncpg "attached to a different loop"
    cross-test-loop error inherent to combining pytest-asyncio's default per-test event
    loop with session-scoped asyncpg-backed SQLAlchemy fixtures
affects: [04-04, packaging]

# Actuals (#2632)
actuals:
  tokens: 2188
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns: [
    "Session-scoped async SQLAlchemy fixtures backed by asyncpg require
     loop_scope=\"session\" on every fixture in the dependency chain AND a class-level
     pytest.mark.asyncio(loop_scope=\"session\") on the consuming test class — asyncpg
     connections are bound to the event loop that created them and error on reuse from a
     different per-test loop, unlike aiosqlite which re-reads the current loop per call",
    "Uniform table-delete reset (not savepoint-rollback) across every SQL-backed
     backend_factory id, keeping contract_suite.py's isolation strategy identical for
     sqlite and postgres"
  ]

key-files:
  created: []
  modified:
    - tests/storage/conftest.py
    - tests/storage/contract_suite.py
    - .planning/phases/04-sql-backend-concurrency-proof/deferred-items.md

key-decisions:
  - "Fixed the asyncpg cross-event-loop RuntimeError (Rule 3 - blocking) by adding
     loop_scope=\"session\" to sqlite_engine, pg_engine, and _reset_sql_tables, plus a
     class-level pytest.mark.asyncio(loop_scope=\"session\") on
     TestStorageContractSuite — not by touching pyproject.toml's shared pytest ini
     config, which risked a merge conflict with the parallel sibling plan (04-03) in
     its own worktree."
  - "No dialect-parity code fixes were needed in store.py — Task 2's full three-way
     regression (51 contract_suite.py cases + 3 more storage tests) passed cleanly on
     the first run after Task 1's fixture wiring landed. The JSON/JSONB empty-payload
     round-trip, DateTime(timezone=True) round-trip, and the dialect-agnostic
     IntegrityError catch in _write_idempotency_record were all already correct from
     Plan 04-01."

patterns-established:
  - "Every session-scoped async fixture backed by a real network-bound driver
     (asyncpg, in contrast to aiosqlite's per-call loop lookup) must declare
     loop_scope=\"session\" explicitly and the consuming test class must too — a
     project-specific pytest-asyncio gotcha now documented inline in
     contract_suite.py for the next SQL-backed fixture that gets added."

requirements-completed: [STORE-03, STORE-04]

coverage:
  - id: D1
    description: "SQLStore's Postgres path is proven correct against the identical,
      shared test suite already proven correct for SQLite — the same 51-case
      contract_suite.py passes for all three backend ids (in-memory, sqlite, postgres)"
    requirement: STORE-04
    verification:
      - kind: integration
        ref: "tests/storage/contract_suite.py#TestStorageContractSuite (all 17 methods,
          all 3 backend_factory ids, 51 cases)"
        status: pass
    human_judgment: false
  - id: D2
    description: "locking.py's pg_advisory_xact_lock branch executes for the first time
      against a genuine Postgres dialect (testcontainers postgres:17), with no state
      leakage between the 17+ parametrized test methods"
    requirement: STORE-03
    verification:
      - kind: integration
        ref: "tests/storage/contract_suite.py -k postgres (17 cases)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The bookings.payload JSON/JSONB column and DateTime(timezone=True)
      columns round-trip correctly on Postgres (empty payload dict returns as {}, stored
      UTC datetime returns UTC-aware)"
    verification:
      - kind: integration
        ref: "tests/storage/contract_suite.py#TestStorageContractSuite (Booking Pydantic
          validation on every postgres-parametrized confirm_hold/cancel_booking case
          would have raised on a None/string payload or naive datetime — none did)"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-09-04
status: complete
---

# Phase 4 Plan 2: Real-Postgres Fixtures & Three-Way Contract Suite Summary

**SQLStore's Postgres dialect path proven correct against the identical, unmodified 51-case shared contract suite already proven correct for SQLite — testcontainers Postgres 17 wired via session-scoped fixtures, no store.py changes needed.**

## Performance

- **Duration:** ~6 min (commit-to-commit)
- **Started:** 2026-09-04T13:01Z (branch base)
- **Completed:** 2026-09-04T13:07Z (Task 2 commit)
- **Tasks:** 2/2
- **Files modified:** 3 (2 test files, 1 deferred-items log)

## Accomplishments
- Added `pg_container`/`pg_engine` session-scoped testcontainers fixtures to
  `tests/storage/conftest.py`, matching `sqlite_engine`'s existing creation pattern
  (dialect-agnostic `metadata.create_all`).
- Extended `backend_factory` to resolve `"postgres"` to `SQLStore(pg_engine)` — same
  class, same constructor shape, no Postgres-specific subclass.
- Extended the autouse `_reset_sql_tables` fixture to reset both `sqlite_engine` and
  `pg_engine` tables before every test — a uniform table-delete strategy across both
  SQL backends.
- Flipped `contract_suite.py`'s parametrize ids to
  `["in-memory", "sqlite", "postgres"]` — the only test-body-adjacent line changed.
- Diagnosed and fixed a real cross-event-loop `RuntimeError` from asyncpg (session-scoped
  fixture's connection bound to a different loop than each per-test default loop) with a
  scoped `loop_scope="session"` fix, not a shared `pyproject.toml` ini change.
- Ran the full three-way regression (51 `contract_suite.py` cases + 3 more storage
  tests = 54, plus 105 project-wide): all green on the first attempt after Task 1's
  fixtures landed — no `store.py` dialect-parity fixes were required.
- `mypy --strict src` clean; every file this plan touched is individually
  `ruff check`-clean (the 6 pre-existing E501 violations from Plan 04-01 re-surface on a
  whole-repo `ruff check`, confirmed byte-for-byte unchanged, already logged and
  out of scope).

## Task Commits

1. **Task 1: Add real-Postgres fixtures and extend the contract-suite parametrization
   to three backends** - `ece4a16` (feat)
2. **Task 2: Full three-way regression and dialect-specific parity fixes** - `f5c2aff`
   (test)

## Files Created/Modified
- `tests/storage/conftest.py` - added `pg_container` (session-scoped
  `PostgresContainer("postgres:17", driver="asyncpg")`) and `pg_engine`
  (session-scoped `AsyncEngine`, schema created via `metadata.create_all`);
  extended `_reset_sql_tables` and `backend_factory` for the new `"postgres"` id;
  added `loop_scope="session"` to `sqlite_engine`, `pg_engine`, and
  `_reset_sql_tables`.
- `tests/storage/contract_suite.py` - parametrize ids extended to
  `["in-memory", "sqlite", "postgres"]`; added a class-level
  `pytestmark = pytest.mark.asyncio(loop_scope="session")` with an inline comment
  explaining why (asyncpg loop-binding).
- `.planning/phases/04-sql-backend-concurrency-proof/deferred-items.md` - logged the
  04-02 re-confirmation of the same 6 pre-existing `ruff` E501 violations and the
  reasoning for why no dialect-parity fix was needed in `store.py`.

## Decisions Made
See `key-decisions` in frontmatter — the `loop_scope="session"` fix (scoped to test
files rather than shared pytest ini config, to avoid a merge conflict with the parallel
04-03 worktree) and the "no store.py changes needed" finding are the two decisions with
real weight this plan made.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] asyncpg "attached to a different loop" RuntimeError on every
postgres-parametrized test**
- **Found during:** Task 1 (`uv run pytest tests/storage/contract_suite.py -k postgres -x`)
- **Issue:** `pg_engine` is a session-scoped async fixture, but pytest-asyncio's default
  per-test event loop scope is `"function"` (the project's `pyproject.toml` has no
  `asyncio_default_fixture_loop_scope` override). Each test function got its own fresh
  event loop, while `pg_engine`'s underlying asyncpg connections stayed bound to
  whichever loop first created them. asyncpg raises `RuntimeError: ... attached to a
  different loop` the moment a later test's loop diverges. `sqlite_engine` (already
  session-scoped since Plan 04-01) never surfaced this because aiosqlite re-reads the
  *current* running loop on every call rather than binding to one loop at connection
  creation time — a real dialect-behavior difference, not a latent bug in the existing
  sqlite wiring.
- **Fix:** Added `loop_scope="session"` to `sqlite_engine`, `pg_engine`, and
  `_reset_sql_tables` (all in `tests/storage/conftest.py`), plus a class-level
  `pytestmark = pytest.mark.asyncio(loop_scope="session")` on
  `TestStorageContractSuite` in `contract_suite.py`, so every test in the suite and
  every fixture it depends on runs on the one shared session-scoped event loop.
  Deliberately did NOT touch `pyproject.toml`'s `[tool.pytest.ini_options]` (a shared
  file the parallel 04-03 worktree may also touch) — the fix is fully contained to the
  two files this plan already owns.
- **Files modified:** `tests/storage/conftest.py`, `tests/storage/contract_suite.py`
- **Verification:** `uv run pytest tests/storage/contract_suite.py -k postgres -x` — 17
  passed (was: 1 error on first postgres test). Full `uv run pytest tests/storage/ -x`
  — 54 passed. Full project `uv run pytest` — 105 passed.
- **Committed in:** `ece4a16` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking, a real pytest-asyncio/asyncpg
interaction bug, not a plan-text gap). No scope creep — the fix is confined to test
infrastructure this plan already owns and does not touch shared config.

## Issues Encountered
None beyond the deviation documented above.

## User Setup Required
None - no external service configuration required. `docker info` confirmed reachable at
plan start (Task 1's `<precondition>`); testcontainers handled the Postgres 17 container
lifecycle end-to-end.

## Next Phase Readiness
- Wave 3 (Plan 04-04, HOLD-02) can build directly on `pg_engine`/`pg_container` without
  re-deriving Postgres fixture wiring — but per RESEARCH.md's Pattern 3, HOLD-02's
  concurrency proof must NOT reuse this plan's `_reset_sql_tables` table-delete
  isolation or any shared connection/transaction; it needs its own fixture opening N
  genuinely independent connections.
- The `loop_scope="session"` pattern documented inline in `contract_suite.py` is now
  the reference for any future SQL-backed async fixture this project adds.
- The 6 pre-existing `ruff` E501 violations remain unresolved (logged, out of scope,
  re-confirmed this plan); a future cleanup task should address them.
- `alembic/` scaffolding (STORE-05) is not yet started — still deferred to a later plan
  in this phase per the roadmap.

---
*Phase: 04-sql-backend-concurrency-proof*
*Completed: 2026-09-04*
