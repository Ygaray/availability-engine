---
phase: 04-sql-backend-concurrency-proof
plan: 03
subsystem: database
tags: [alembic, migrations, sqlite, postgres, aiosqlite, asyncio, testcontainers]

# Dependency graph
requires:
  - phase: 04-sql-backend-concurrency-proof
    plan: "04-01"
    provides: "src/availability_engine/storage/sql/models.py's shared MetaData
      object — alembic/env.py imports target_metadata directly from it, never
      hand-copied"
provides:
  - "Versioned Alembic migrations from the first SQL commit (alembic.ini,
    alembic/env.py, alembic/versions/0001_initial_schema.py), consumer-run
    rather than auto-applied on import (D-03), proven to apply cleanly and
    identically against both SQLite and a real testcontainers Postgres"
  - "Empirical confirmation of D-05: aiosqlite's per-connection background
    thread keeps the asyncio event loop responsive during a query, verified
    via an explicit ticker/slow-query interleave test at the pinned
    aiosqlite==0.22.1 version"
affects: [packaging]

# Actuals (#2632)
actuals:
  tokens: 4426
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns: [
    "alembic/env.py's target_metadata imports the exact same MetaData object
     store.py's engine uses for metadata.create_all in test fixtures — never
     a second, hand-copied MetaData",
    "render_as_batch=True set globally in env.py's do_run_migrations — safe
     on Postgres too, since batch mode only actually activates when
     SQLite's limited ALTER support requires it",
    "Migration-apply tests keep alembic's env.py-driven asyncio.run() calls
     as sync test functions (not `async def`), avoiding a nested-event-loop
     conflict with pytest-asyncio's auto mode; where async inspection is
     needed afterward, a small async helper is invoked via its own top-level
     asyncio.run()"
  ]

key-files:
  created:
    - alembic.ini
    - alembic/env.py
    - alembic/script.py.mako
    - alembic/versions/0001_initial_schema.py
    - tests/test_migrations.py
    - tests/test_aiosqlite_loop_responsiveness.py

key-decisions:
  - "Added alembic/script.py.mako (not in the plan's files_modified list) —
     the standard Alembic scaffold template needed for any future `alembic
     revision` authoring. Without it, a consumer or future plan generating a
     migration 2 (a real ALTER, where batch mode actually matters) would hit
     a missing-template error. Rule 2 (missing critical) — zero-risk
     addition, doesn't touch any file the plan claims."
  - "Postgres table-name inspection in test_migrations.py uses an async
     SQLAlchemy engine + connection.run_sync bridge, not a plain sync
     sa.create_engine() connection — this project's dependency set installs
     only the asyncpg driver (no sync psycopg2/psycopg), so a sync
     postgresql:// URL would fail to connect at all."
  - "test_alembic_upgrade_head_creates_postgres_schema is a plain sync test
     function (not `async def`), even though it exercises async code paths
     internally. alembic's env.py calls asyncio.run() itself inside
     command.upgrade() — if the test function were wrapped in
     pytest-asyncio's own event loop (auto mode), that nested asyncio.run()
     call raises 'cannot be called from a running event loop'. A sync test
     body lets alembic's internal asyncio.run() and a separate
     asyncio.run()-based inspection helper each own their own top-level
     event loop in turn."

patterns-established:
  - "alembic/ lives at the repo root (Alembic's default location), never
     buried inside src/ or a test-only directory — RESEARCH.md Pitfall 4:
     Phase 5's packaging work explicitly depends on finding it here."

requirements-completed: [STORE-05]

coverage:
  - id: D1
    description: "alembic upgrade head, applied programmatically against a
      fresh SQLite file, creates all four tables (resources, holds,
      bookings, idempotency) with no errors"
    requirement: STORE-05
    verification:
      - kind: integration
        ref: "tests/test_migrations.py#test_alembic_upgrade_head_creates_sqlite_schema"
        status: pass
    human_judgment: false
  - id: D2
    description: "alembic upgrade head, applied against a fresh throwaway
      testcontainers Postgres database, creates the same four tables,
      independent of Plan 04-02's fixtures"
    requirement: STORE-05
    verification:
      - kind: integration
        ref: "tests/test_migrations.py#test_alembic_upgrade_head_creates_postgres_schema"
        status: pass
    human_judgment: false
  - id: D3
    description: "aiosqlite's per-connection background thread keeps the
      asyncio event loop responsive during a query (D-05), verified via an
      explicit ticker/slow-query interleave assertion, not assumed from the
      driver's documentation"
    verification:
      - kind: unit
        ref: "tests/test_aiosqlite_loop_responsiveness.py#test_ticker_advances_during_slow_aiosqlite_query"
        status: pass
    human_judgment: false

duration: 3min
completed: 2026-09-04
status: complete
---

# Phase 4 Plan 3: Alembic Migrations & aiosqlite Loop-Responsiveness Proof Summary

**Versioned Alembic migrations (SQLite + real testcontainers Postgres, both proven identical) plus an empirical, non-assumed confirmation that aiosqlite keeps the asyncio event loop responsive during a query (D-05).**

## Performance

- **Duration:** ~3 min (commit-to-commit)
- **Started:** 2026-09-04T13:04:09-06:00 (Task 1 commit)
- **Completed:** 2026-09-04T13:06:51-06:00 (Task 3 commit)
- **Tasks:** 3/3
- **Files created:** 6 (alembic.ini, alembic/env.py, alembic/script.py.mako, alembic/versions/0001_initial_schema.py, tests/test_migrations.py, tests/test_aiosqlite_loop_responsiveness.py)

## Accomplishments
- Stood up the Alembic scaffold at the repo root (`alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial_schema.py`), consumer-run rather than auto-applied on import (D-03) — nothing in `alembic/env.py` triggers a migration at import time, and no `SQLStore.__init__`/`AvailabilityEngine.__init__` path calls it (T-04-05, verified by construction).
- `alembic/env.py`'s `target_metadata` imports directly from `src/availability_engine/storage/sql/models.py`'s shared `MetaData` object — the exact same object `store.py`'s engine uses for `metadata.create_all` in test fixtures. No hand-copied schema exists to drift.
- `alembic upgrade head` proven to apply cleanly and identically against a fresh temp-file SQLite database and, independently, a fresh throwaway testcontainers Postgres 17 container — both produce the same four tables (`resources`, `holds`, `bookings`, `idempotency`), closing STORE-05 and Success Criterion #4.
- Empirically confirmed D-05 rather than assuming it from aiosqlite's documentation: a ticker coroutine incrementing a counter every 0.01s, run concurrently via `asyncio.gather` with an aiosqlite query carrying an artificial ~0.3s delay, advanced ~30 times during the query (elapsed ~0.31s) — proving the event loop stayed responsive throughout, not just that the query eventually completed.
- Full project test suite (91 tests) passes; `ruff check` and `mypy --strict` clean on every file this plan touched.

## Task Commits

1. **Task 1: Alembic scaffold and SQLite migration-apply verification** - `2ef3996` (feat)
2. **Task 2: Postgres migration-apply parity** - `1d075ea` (test)
3. **Task 3: D-05 — verify aiosqlite's async driver does not block the event loop** - `abfc152` (test)

## Files Created/Modified
- `alembic.ini` - repo-root Alembic config (Alembic's default location per RESEARCH.md Pitfall 4), `script_location = alembic`, a placeholder (never real) `sqlalchemy.url`.
- `alembic/env.py` - async `run_sync` bridge (`do_run_migrations` + `run_migrations_online_async`), `render_as_batch=True`, `target_metadata` imported directly from `models.py`.
- `alembic/script.py.mako` - standard Alembic revision template (Rule 2 addition — needed for any future `alembic revision` authoring; not in the plan's literal file list but zero-risk and non-overlapping with anything else).
- `alembic/versions/0001_initial_schema.py` - explicit `op.create_table` calls for all four tables, mirroring `models.py` column-for-column (names, types, nullability, indexes); bare `create_table` needs no `batch_alter_table` wrapper.
- `tests/test_migrations.py` - `test_alembic_upgrade_head_creates_sqlite_schema` (Task 1) and `test_alembic_upgrade_head_creates_postgres_schema` (Task 2), each running `alembic.command.upgrade(cfg, "head")` against a fresh backend and asserting all four table names via `sqlalchemy.inspect(...).get_table_names()`.
- `tests/test_aiosqlite_loop_responsiveness.py` - `test_ticker_advances_during_slow_aiosqlite_query`, implementing RESEARCH.md's Pitfall 2 recipe (ticker + UDF-based slow query via `asyncio.gather`).

## Decisions Made
See `key-decisions` in frontmatter — the `script.py.mako` addition, the async-engine-based Postgres table inspection (only `asyncpg` is installed, no sync driver), and the sync-test-function pattern to avoid a nested-`asyncio.run()` conflict with `pytest-asyncio`'s auto mode are the three decisions with real design weight.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added `alembic/script.py.mako`**
- **Found during:** Task 1 (Alembic scaffold)
- **Issue:** Not listed in the plan's `files_modified` frontmatter. Without it, `alembic revision` (needed to author any future migration, e.g. an actual `ALTER` where `batch_alter_table` mode matters) fails with a missing-template error.
- **Fix:** Added the standard Alembic-generated `script.py.mako` template.
- **Files modified:** `alembic/script.py.mako` (new file, zero overlap with any other file)
- **Verification:** File follows Alembic's own default template shape; not exercised by this plan's tests (no new migration was authored), but unblocks future migration authoring.
- **Committed in:** `2ef3996` (Task 1 commit)

**2. [Rule 3 - Blocking] `asyncio.run() cannot be called from a running event loop` in the Postgres migration test**
- **Found during:** Task 2 (writing `test_alembic_upgrade_head_creates_postgres_schema`)
- **Issue:** First draft made the test `async def` (to `await` an async-engine inspection). `alembic`'s `env.py` calls `asyncio.run()` internally inside `command.upgrade()`, which raised `RuntimeError: asyncio.run() cannot be called from a running event loop` once the test itself was already running inside `pytest-asyncio`'s auto-mode event loop.
- **Fix:** Changed the test to a plain sync function; table inspection (which does need an async engine, since only the `asyncpg` driver is installed) is delegated to a small async helper invoked via its own top-level `asyncio.run()`, called only after `command.upgrade()` has already returned.
- **Files modified:** `tests/test_migrations.py`
- **Verification:** `uv run pytest tests/test_migrations.py -x` — both SQLite and Postgres cases pass.
- **Committed in:** `1d075ea` (Task 2 commit)

**3. [Rule 3 - Blocking] Postgres table inspection needed an async engine, not a sync connection**
- **Found during:** Task 2
- **Issue:** The SQLite test's pattern (a plain `sa.create_engine()` sync connection for read-only inspection) doesn't work for Postgres in this repo — no sync driver (`psycopg2`/`psycopg`) is installed, only `asyncpg`. A sync `postgresql://` URL fails to connect.
- **Fix:** Used `create_async_engine` + `connection.run_sync(lambda sync_conn: sa.inspect(sync_conn).get_table_names())` instead.
- **Files modified:** `tests/test_migrations.py`
- **Verification:** Same as above.
- **Committed in:** `1d075ea` (Task 2 commit)

---

**Total deviations:** 3 (1 Rule 2 — missing critical scaffold file; 2 Rule 3 — blocking asyncio/driver issues discovered while writing the Postgres test). All fixed inline, verified, and committed within their originating task's commit.

## TDD Gate Compliance

Task 3 carries `tdd="true"` in its frontmatter, but this task is a **verification test against pre-existing third-party (aiosqlite) library behavior**, not new production behavior this plan builds. There is no `<implementation>` block in the plan text (only `<action>`, which fully specifies the test file itself), and no source file under `src/` was created or modified for this task — the `<files>` list names only the test file.

Per the standard RED/GREEN/REFACTOR flow, a RED-phase test that passes unexpectedly should trigger investigation before proceeding — but here the test's very purpose is to empirically confirm a claim (D-05) that RESEARCH.md already assessed as likely true from aiosqlite's own documentation. The test passing on first run, with a concrete elapsed/tick correlation (~0.31s elapsed, ~30 ticks at a 0.01s interval — consistent with an unblocked loop), **is** the correct and expected outcome, not a sign the test is broken or the feature already exists elsewhere. A single `test(04-03): ...` commit was made rather than an artificial RED-then-GREEN split, since no production code changed.

## Issues Encountered
None beyond the two Rule 3 fixes documented above (both resolved within Task 2, before that task's commit).

## User Setup Required
None — Docker was already running and reachable (`docker info` exit 0) for Task 2's precondition; no external service configuration required.

## Next Phase Readiness
- STORE-05 is fully closed: `alembic upgrade head` is proven to apply cleanly and identically on both SQLite and Postgres.
- `alembic/` sits at the repo root, ready for Phase 5's packaging work to force-include it into the wheel (RESEARCH.md Pitfall 4 — Phase 5's own gray area explicitly depends on this layout existing).
- D-05 is empirically closed — no further verification of aiosqlite's loop responsiveness is needed at the pinned `aiosqlite==0.22.1` version.
- This plan touched no files Plan 04-02 depends on (deliberately independent throwaway Postgres fixture, per the plan's own design) — zero merge-conflict risk with 04-02's wave-2 work.

---
*Phase: 04-sql-backend-concurrency-proof*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created files verified present on disk:
- `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`,
  `alembic/versions/0001_initial_schema.py`, `tests/test_migrations.py`,
  `tests/test_aiosqlite_loop_responsiveness.py`,
  `.planning/phases/04-sql-backend-concurrency-proof/04-03-SUMMARY.md`

All task commits verified present in `git log --oneline --all`:
- `2ef3996`, `1d075ea`, `abfc152`, `ab210ef`
