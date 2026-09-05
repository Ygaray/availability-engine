---
phase: 04-sql-backend-concurrency-proof
plan: 01
subsystem: database
tags: [sqlalchemy, aiosqlite, asyncpg, alembic, sqlite, postgres, storage-backend, concurrency]

# Dependency graph
requires:
  - phase: 03-idempotency-cancellation
    provides: the InMemoryStore reference implementation (fingerprinting, idempotency-table
      shape, active-entries primitive) this SQL backend faithfully ports
provides:
  - A complete SQLStore implementing all seven StorageBackend Protocol methods against
    SQLAlchemy Core, proven end-to-end on SQLite
  - The one dialect-branch-point architecture (locking.py) — Postgres advisory lock vs.
    SQLite BEGIN IMMEDIATE — that Wave 2 (real Postgres) and Wave 3 (concurrency proof)
    build on directly
  - The shared contract_suite.py now runs, unmodified in every test body, against both
    InMemoryStore and SQLStore-on-SQLite
affects: [04-02, 04-03, 04-04, packaging]

# Actuals (#2632)
actuals:
  tokens: 9218
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: [sqlalchemy>=2.0,<2.1, asyncpg==0.31.0, aiosqlite==0.22.1, alembic==1.19.1,
    "testcontainers[postgres]==4.15.0 (dev)"]
  patterns: [
    "Dialect-branch confined to one module (locking.py) — every other SQL query in
     store.py is dialect-agnostic SQLAlchemy Core",
    "SAVEPOINT (begin_nested) around an idempotency-row INSERT so a same-key race's
     IntegrityError doesn't abort the enclosing Postgres transaction",
    "Indirect pytest parametrization (backend_factory fixture reading request.param) so
     a shared contract suite's static parametrize list can add a runtime-fixture-backed
     backend without rewriting any test body"
  ]

key-files:
  created:
    - src/availability_engine/storage/sql/models.py
    - src/availability_engine/storage/sql/locking.py
    - src/availability_engine/storage/sql/store.py
    - tests/storage/test_sql_store.py
  modified:
    - pyproject.toml
    - tests/storage/conftest.py
    - tests/storage/contract_suite.py
    - tests/storage/test_protocol_conformance.py

key-decisions:
  - "Superseded CONTEXT.md's D-01 (and the Runtime Decisions' restated Postgres SELECT ...
     FOR UPDATE): both are unsafe against genuinely concurrent Postgres connections for
     this schema (FOR UPDATE cannot lock a row that does not yet exist — a phantom-insert
     race). Adopted a Postgres transaction-scoped advisory lock (pg_advisory_xact_lock,
     keyed on (resource_id, slot_start)) as place_hold's first statement instead — a
     schema-preserving, READ COMMITTED-preserving correction per RESEARCH.md's documented
     finding, empirically arbitrated by Wave 3's HOLD-02 concurrency test."
  - "Wrapped the idempotency-row INSERT in a SAVEPOINT (conn.begin_nested()), not just a
     bare try/except IntegrityError — on Postgres an uncaught statement error aborts the
     entire enclosing transaction, so the re-SELECT-after-conflict recovery path needs a
     savepoint boundary to keep the outer transaction (and its advisory lock) usable.
     Not spelled out verbatim in the plan text but required for the try/except pattern to
     actually work portably across both dialects."
  - "Normalized every datetime read back from either dialect via a small _ensure_utc
     helper: SQLite's DATETIME type drops tzinfo on round-trip (rows return naive), while
     Postgres's DateTime(timezone=True) round-trips aware. Since every write is already
     UTC-aware wall-clock at construction time, a naive read value's wall-clock fields ARE
     already UTC — attach the label rather than convert. Needed to satisfy contracts.py's
     UtcDatetime (AwareDatetime) validation on every SQLite-sourced Hold/Booking."
  - "save_resource uses a portable select-then-insert-or-update (not dialect-specific
     INSERT ... ON CONFLICT), keeping the upsert dialect-agnostic per the 'one branch
     point only' architecture."

patterns-established:
  - "locking.py is the ONLY file in the SQL backend permitted to branch on
     conn.engine.dialect.name — every future SQL query added to store.py must stay
     dialect-agnostic Core."
  - "SQLStore's private _get_active_entries(conn, ...) is the one shared active-entries
     primitive — place_hold's capacity check and the public get_active_entries Protocol
     method both call it on the same connection, never a duplicate scan."

requirements-completed: [STORE-03, STORE-04]

coverage:
  - id: D1
    description: "SQLStore satisfies the StorageBackend Protocol structurally and
      functionally against SQLite, for all seven Protocol methods"
    requirement: STORE-03
    verification:
      - kind: unit
        ref: "tests/storage/test_protocol_conformance.py#test_sqlstore_satisfies_protocol"
        status: pass
      - kind: integration
        ref: "tests/storage/test_sql_store.py#test_place_hold_end_to_end_sqlite"
        status: pass
    human_judgment: false
  - id: D2
    description: "The shared contract_suite.py test class (34 test cases across 17
      methods) passes for both in-memory and sqlite backend ids, with only the
      parametrize decorator changed and one disclosed test-body line fixed for
      cross-backend portability"
    requirement: STORE-04
    verification:
      - kind: unit
        ref: "tests/storage/contract_suite.py#TestStorageContractSuite (all methods,
          both backend_factory ids)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Placing a hold on a capacity-1 SQLite-backed resource succeeds once and
      raises CapacityExhaustedError on a second attempt for the same slot, via a real SQL
      round-trip"
    verification:
      - kind: integration
        ref: "tests/storage/test_sql_store.py#test_place_hold_end_to_end_sqlite"
        status: pass
    human_judgment: false

duration: 3min
completed: 2026-09-04
status: complete
---

# Phase 4 Plan 1: SQL Schema, Dialect Locking & SQLite-Proven SQLStore Summary

**Complete `SQLStore` (all 7 `StorageBackend` Protocol methods) over a SQLAlchemy Core
schema — `resources`/`holds`/`bookings`/`idempotency` tables — proven end-to-end against
real SQLite, with a Postgres-safe transaction-scoped advisory-lock design ready for Wave 2.**

## Performance

- **Duration:** ~3 min (commit-to-commit)
- **Started:** 2026-09-04T12:56Z (Task 1 commit)
- **Completed:** 2026-09-04T12:59Z (Task 2 commit)
- **Tasks:** 2/2
- **Files modified:** 10 (4 created under `src/`, 1 created under `tests/`, 4 modified,
  1 deferred-items log)

## Accomplishments
- Stood up the full SQL storage architecture: `models.py` (4 tables mirroring the
  in-memory `_holds`/`_bookings` split plus a composite-PK `idempotency` table),
  `locking.py` (the one dialect-branch point), and `store.py` (`SQLStore`, a faithful
  method-for-method SQL port of `memory.py`).
- Proved one real end-to-end path — `place_hold` → `CapacityExhaustedError` on a
  capacity-1 resource — against a genuine SQL round-trip through SQLite (WAL mode,
  `BEGIN IMMEDIATE`, `NullPool`), not an in-memory dict.
- Wired the existing 17-method shared `contract_suite.py` to run unmodified (aside from
  the parametrize decorator and one disclosed portability fix) against both
  `InMemoryStore` and `SQLStore`-on-SQLite — 34 passing test cases.
- Superseded CONTEXT.md's D-01 with a documented, RESEARCH.md-backed Postgres
  transaction-scoped advisory-lock design, ready for Wave 2/3 to exercise against real
  Postgres.
- All 88 project tests pass; `mypy --strict src` clean; every file this plan touched is
  individually `ruff check`-clean.

## Task Commits

1. **Task 1: Tracer — SQL schema, dialect locking, and a complete SQLStore proven
   end-to-end on SQLite** - `63df130` (feat)
2. **Task 2: Expansion — wire the full shared contract suite to SQLite, fix its one
   non-portable test** - `d159f87` (test)

_Note: this plan's `type="tracer"` Task 1 was committed and its `<verify>` re-run
green before Task 2 began, per the tracer feedback gate._

## Files Created/Modified
- `pyproject.toml` - added sqlalchemy/asyncpg/aiosqlite/alembic (core) and
  testcontainers[postgres] (dev group), pinned per RESEARCH.md's Package Legitimacy
  Audit — the full Phase 4 dependency set, so no later Wave-2 plan needs to touch it.
- `src/availability_engine/storage/sql/models.py` - SQLAlchemy Core `MetaData` + 4
  `Table` objects (resources/holds/bookings/idempotency), column names mirroring
  `contracts.py` exactly.
- `src/availability_engine/storage/sql/locking.py` - the one dialect-branch point:
  `acquire_postgres_slot_lock` (advisory lock, named bind params) and
  `attach_sqlite_begin_immediate` (two-event-listener BEGIN IMMEDIATE recipe + WAL +
  busy_timeout).
- `src/availability_engine/storage/sql/store.py` - `SQLStore`, implementing all seven
  `StorageBackend` Protocol methods; idempotency fingerprinting reused (imported) from
  `memory.py`, never re-derived.
- `tests/storage/conftest.py` - `sqlite_engine` (session-scoped, temp-file, WAL,
  `NullPool`), `_reset_sql_tables` (autouse), `backend_factory` (indirect-parametrize
  fixture).
- `tests/storage/test_sql_store.py` - the tracer's dedicated end-to-end smoke test.
- `tests/storage/contract_suite.py` - parametrize decorator changed to indirect
  `["in-memory", "sqlite"]`; one test body's private-attribute assertion replaced with a
  protocol-safe `HoldNotFoundError` check.
- `tests/storage/test_protocol_conformance.py` - added
  `test_sqlstore_satisfies_protocol`.
- `.planning/phases/04-sql-backend-concurrency-proof/deferred-items.md` - logged 6
  pre-existing (Phase-3-vintage) `ruff` E501 violations, out of this plan's scope.

## Decisions Made
See `key-decisions` in frontmatter — the D-01 supersession, the SAVEPOINT-around-INSERT
recovery pattern, the `_ensure_utc` datetime normalization, and the portable
select-then-insert-or-update upsert shape are the four decisions with real design weight.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] SAVEPOINT (begin_nested) around the idempotency-row
INSERT, not a bare try/except**
- **Found during:** Task 1 (`place_hold`/`confirm_hold` idempotency-write path)
- **Issue:** The plan's text describes catching a driver-level `IntegrityError` on a
  same-key race and re-SELECTing. On Postgres, an uncaught statement error inside a
  transaction aborts the *entire* transaction — every subsequent statement fails until
  `ROLLBACK` — so a bare try/except around the INSERT would make the recovery re-SELECT
  itself fail once Postgres is exercised in Wave 2/3.
- **Fix:** Wrapped the INSERT in `async with conn.begin_nested():` (a SAVEPOINT), so only
  that statement's failure rolls back, leaving the outer transaction (and its advisory
  lock) usable for the recovery re-SELECT.
- **Files modified:** `src/availability_engine/storage/sql/store.py`
  (`_write_idempotency_record`)
- **Verification:** `tests/storage/contract_suite.py`'s idempotency-conflict tests pass
  against SQLite this wave; the SAVEPOINT boundary is a no-op-safe addition on SQLite
  (also supports SAVEPOINT) and is the documented-correct pattern for Postgres, to be
  empirically exercised in Wave 2/3.
- **Committed in:** `63df130` (Task 1 commit)

**2. [Rule 2 - Missing Critical] `_ensure_utc` datetime normalization on every SQL read**
- **Found during:** Task 1 (constructing `Hold`/`Booking` from SQLite query rows)
- **Issue:** Not explicitly called out in the plan. SQLite's `DateTime(timezone=True)`
  type drops tzinfo on round-trip (rows return naive `datetime` objects); `contracts.py`'s
  `UtcDatetime` (`AwareDatetime`) validator rejects naive datetimes outright, which would
  crash every SQLite-backed read.
- **Fix:** Added `_ensure_utc()`, attaching the UTC label to a naive value (since every
  write is already UTC wall-clock at construction time) or converting an already-aware
  value (Postgres) to UTC. Applied uniformly to every `slot_start`/`slot_end`/
  `expires_at` read.
- **Files modified:** `src/availability_engine/storage/sql/store.py`
- **Verification:** `test_place_hold_end_to_end_sqlite` and the full 34-case contract
  suite construct/compare `Hold`/`Booking` objects successfully against SQLite.
- **Committed in:** `63df130` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 2 — missing critical correctness behavior
for cross-dialect portability). Both are prerequisites for Wave 2/3's Postgres path to
work correctly, not scope creep — the plan's own architecture ("one SQL implementation,
two dialects") requires them.

## Issues Encountered
- `uv run ruff check` (whole repo, per the plan's literal `<verify>` command) surfaces 6
  pre-existing E501 violations in `src/availability_engine/storage/memory.py` and
  `tests/storage/contract_suite.py` that predate this plan entirely (confirmed via `git
  diff <phase-4-base-commit>` — zero diff on the offending lines, landed in Phase 3).
  Per the SCOPE BOUNDARY rule, these are out of scope and were logged to
  `deferred-items.md` rather than fixed. Every file this plan actually created or
  modified is individually `ruff check`-clean.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 2 (Plan 04-02/04-03) can build directly on `SQLStore`/`locking.py`/`models.py`
  without touching `pyproject.toml` again (the full Phase 4 dependency set is already
  installed).
- The `pg_advisory_xact_lock` design and the SAVEPOINT idempotency-recovery pattern are
  in place and ready for real-Postgres exercise; Wave 3's HOLD-02 concurrency proof is the
  empirical arbiter of the D-01 supersession.
- `alembic/` scaffolding (STORE-05) is not yet started — deferred to a later plan in this
  phase per the roadmap.
- The 6 pre-existing `ruff` E501 violations logged in `deferred-items.md` remain
  unresolved; a future cleanup task should address them.

---
*Phase: 04-sql-backend-concurrency-proof*
*Completed: 2026-09-04*
