---
phase: 04-sql-backend-concurrency-proof
fixed_at: 2026-09-04T19:33:44Z
review_path: .planning/phases/04-sql-backend-concurrency-proof/04-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: resolved
---

# Phase 4: Code Review Fix Report

**Fixed at:** 2026-09-04T19:33:44Z
**Source review:** .planning/phases/04-sql-backend-concurrency-proof/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (fix_scope: critical_warning — 2 critical, 4 warning; the 2 info-level
  findings, IN-01/IN-02, were out of scope for this run)
- Fixed: 6
- Skipped: 0

**Verification:** After all fixes, ran the full test suite (`uv run pytest -x -q --tb=short`,
114 tests including the real-Postgres concurrency proof suite via testcontainers/Docker) and
`uv run mypy --strict src` — both clean. Additionally reproduced the CR-01 regression manually
(temporarily reverted the fix, confirmed the new concurrency test fails, restored the fix) to
confirm the added test coverage is load-bearing, not just green-by-construction.

## Fixed Issues

### CR-01: `confirm_hold` materializes a Booking without checking whether its hold-delete actually matched a row

**Files modified:** `src/availability_engine/storage/sql/store.py`
**Commit:** `66bf076`
**Applied fix:** `confirm_hold`'s `DELETE FROM holds` now captures its `Result` and checks
`rowcount == 0` before proceeding to insert a `Booking` from the (now possibly stale) `hold_row`
snapshot. On `rowcount == 0` (hold concurrently released/re-confirmed/expired-and-reaped between
the initial `SELECT` and this `DELETE`), raises `HoldNotFoundError(hold_id)` instead — matching
`cancel_booking`'s existing rowcount-check pattern in the same file and `memory.py`'s
`HoldNotFoundError` semantics exactly. Also fixes the secondary manifestation (two truly
concurrent `confirm_hold(hold_id)` calls for the same id with no `idempotency_key` — the losing
call now cleanly raises `HoldNotFoundError` instead of a raw uncaught `IntegrityError`).

### CR-02: SQLite's write-serialization fix is never attached outside test fixtures

**Files modified:** `src/availability_engine/storage/sql/locking.py`,
`src/availability_engine/storage/sql/store.py`
**Commit:** `a666e80`
**Applied fix:** `SQLStore.__init__` now calls `attach_sqlite_begin_immediate(engine)`
automatically whenever `engine.sync_engine.dialect.name == "sqlite"`, so the "obvious"
construction path (`SQLStore(create_async_engine("sqlite+aiosqlite:///..."))`) is phantom-safe by
default rather than requiring every consumer to discover and call the listener-attach function
themselves. `attach_sqlite_begin_immediate` was made idempotent (tracked via a process-wide
`weakref.WeakSet[Engine]`, since SQLAlchemy's `Engine` has no built-in `.info` dict attribute
usable for this — confirmed via `mypy --strict` catching the incorrect first attempt) so calling
it more than once against the same physical engine (e.g. once from a test fixture, then again from
every `SQLStore(sqlite_engine)` constructed against that same session-scoped engine) never stacks
duplicate `"connect"`/`"begin"` listeners or issues `BEGIN IMMEDIATE` more than once per
transaction.

### WR-01: `save_resource` has an unguarded check-then-write race

**Files modified:** `src/availability_engine/storage/sql/store.py`
**Commit:** `336f751`
**Applied fix:** The `INSERT` branch is now scoped to a `SAVEPOINT` (`conn.begin_nested()`,
mirroring `_write_idempotency_record`'s existing pattern in the same file) and wrapped in a
`try/except IntegrityError` that falls back to the `UPDATE` path on conflict — so two concurrent
`save_resource()` calls for a not-yet-persisted `resource.id` resolve gracefully (last-write-wins
via `UPDATE`) instead of the losing call raising a raw, unhandled, driver-level `IntegrityError`.

### WR-02: `SQLStore`'s idempotency fingerprint depends on a "private" helper imported from a sibling module

**Files modified:** `src/availability_engine/storage/_shared.py` (new),
`src/availability_engine/storage/memory.py`, `src/availability_engine/storage/sql/store.py`
**Commit:** `9f5b9d0`
**Applied fix:** Created `availability_engine.storage._shared` (exactly the module name suggested
in the review) housing `_fingerprint`; both `memory.py` and `sql/store.py` now import it from
there instead of `sql/store.py` reaching into `memory.py`'s internals. Makes the cross-backend
idempotency-fingerprint contract explicit rather than incidental. `memory.py`'s now-unused
`hashlib` import was removed as part of the move.

### WR-03: `place_hold`'s "authoritative capacity" re-read silently trusts the caller for unregistered resources

**Files modified:** `src/availability_engine/storage/sql/store.py`, `tests/storage/contract_suite.py`
**Commit:** `8be1107`
**Applied fix:** Chose the review's second option (document + test) over raising, because
`memory.py` already has an identical, explicitly-intentional fallback ("Fall back to the
caller-supplied `capacity` only if the resource isn't tracked here — shouldn't happen via the
engine facade, which already validates it"), and `engine.py`'s `AvailabilityEngine.place_hold`
does in fact call `get_resource`/raise `ResourceNotFoundError` before ever reaching
`storage.place_hold` — confirmed by reading `engine.py`. Raising in `SQLStore` alone would have
broken behavioral parity between backends without closing any reachable gap via the facade.
Expanded the code comment in `sql/store.py` to state this explicitly (referencing `engine.py`) and
added `test_place_hold_trusts_caller_capacity_for_unregistered_resource` to `contract_suite.py`,
parametrized across all three backends (in-memory/sqlite/postgres), pinning the fallback as a
deliberate, tested contract.

### WR-04: SQL package `__init__.py` exports nothing

**Files modified:** `src/availability_engine/storage/sql/__init__.py`
**Commit:** `2eea092`
**Applied fix:** Re-exported `SQLStore`, `metadata`, `attach_sqlite_begin_immediate`, and
`acquire_postgres_slot_lock` from the package `__init__.py` with an explicit `__all__`. Verified
no circular-import regression: `sql/store.py` itself does `from availability_engine.storage.sql
import models`, so the `__init__.py` import order (locking → models → store) matters — `models` is
fully imported (and thus set as a package attribute) before `store` is imported, so `store.py`'s
own `from ... import models` resolves against the already-populated attribute rather than
re-triggering `__init__.py`. Confirmed both `from availability_engine.storage.sql import SQLStore`
and the pre-existing `from availability_engine.storage.sql.store import SQLStore` direct-import
path work correctly.

## Additional test coverage (beyond REVIEW.md findings)

Per the task's explicit request to extend test coverage for the CR-01 race "if feasible within
scope": added `test_concurrent_confirm_and_release_never_leaves_phantom_booking` to
`tests/storage/test_concurrency_proof.py` (**commit `6ccfc0f`**, not committed against a
REVIEW.md finding ID). Races real, genuinely-concurrent `confirm_hold`/`release_hold` calls
against the same hold over 50 iterations against a real Postgres container, and asserts the CR-01
invariant: whenever `confirm_hold` loses the race (raises `HoldNotFoundError`), the slot must show
zero active entries — never a leftover phantom `Booking`. Manually verified this test is
load-bearing by temporarily reverting the CR-01 fix locally: the reverted code fails this test
(a later `place_hold` in the loop spuriously raises `CapacityExhaustedError` because a phantom
`Booking` from an earlier race iteration still occupies the slot's capacity), confirming the test
would have caught this exact bug. The fix was restored immediately after and the full suite
re-verified clean.

## Skipped Issues

None — all 6 in-scope findings (CR-01, CR-02, WR-01, WR-02, WR-03, WR-04) were fixed. IN-01 and
IN-02 were out of scope for this run (`fix_scope: critical_warning`) and were left untouched.

---

_Fixed: 2026-09-04T19:33:44Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
