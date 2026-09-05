---
phase: 05-packaging-docs-v1-release
plan: 02
subsystem: engine
tags: [asyncio, sync-facade, threading, run-coroutine-threadsafe]

# Dependency graph
requires: []
provides:
  - "src/availability_engine/sync.py::SyncAvailabilityEngine -- background-thread persistent-event-loop bridge over AvailabilityEngine"
  - "SyncAvailabilityEngine re-exported from availability_engine.__init__ alongside AvailabilityEngine"
  - "tests/test_sync_facade.py -- loop-in-loop regression proof (Pitfall 3), close() cleanup proof, boundary-validation proof"
affects: [05-03, examples/chatbot_adapter, release]

# Actuals (#2632)
actuals:
  tokens: 2425
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Background-thread persistent asyncio event loop + asyncio.run_coroutine_threadsafe(coro, loop).result() as the only safe async->sync bridge for a caller that may itself already be inside a running event loop -- never asyncio.run() per call"
    - "threading.Event-gated startup handshake (thread sets the event from inside _run_loop, right after asyncio.set_event_loop(), before run_forever()) to close the loop-not-yet-created startup race"

key-files:
  created:
    - src/availability_engine/sync.py
    - tests/test_sync_facade.py
  modified:
    - src/availability_engine/__init__.py

key-decisions:
  - "Made _call generic over TypeVar _T (Coroutine[Any, Any, _T] -> _T) rather than Any -- keeps every public method's return type mypy --strict clean without a cast() at each call site"
  - "Test D (loop-in-loop) intentionally passed on first run with no separate fix step -- Task 1's implementation already used run_coroutine_threadsafe correctly, so Task 2 is a pure regression-proof commit, not a RED/GREEN pair (documented in TDD Gate Compliance below)"

patterns-established:
  - "Zero exception translation/logging in the sync bridge module itself (T-05-03) -- engine exceptions propagate unchanged through future.result()'s re-raise"

requirements-completed: [PKG-01]

coverage:
  - id: D1
    description: "A caller inside an already-running asyncio event loop can call a SyncAvailabilityEngine method without raising RuntimeError: asyncio.run() cannot be called from a running event loop"
    requirement: "PKG-01"
    verification:
      - kind: unit
        ref: "tests/test_sync_facade.py::test_sync_facade_callable_from_inside_running_event_loop"
        status: pass
    human_judgment: false
  - id: D2
    description: "SyncAvailabilityEngine.close() stops its background thread within a bounded timeout"
    requirement: "PKG-01"
    verification:
      - kind: unit
        ref: "tests/test_sync_facade.py::test_close_stops_background_thread"
        status: pass
    human_judgment: false
  - id: D3
    description: "The sync facade never logs or interpolates payload/details into any exception message or log line -- forwards engine exceptions unchanged"
    requirement: "PKG-01"
    verification:
      - kind: code-review
        ref: "src/availability_engine/sync.py -- no logging import, no exception translation, module docstring documents the constraint"
        status: pass
    human_judgment: false
  - id: D4
    description: "Naive (non-UTC) datetimes passed through the sync facade still raise the same validation error the async engine raises at its own boundary"
    requirement: "PKG-01"
    verification:
      - kind: unit
        ref: "tests/test_sync_facade.py::test_naive_datetime_raises_same_boundary_error"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-09-04
status: complete
---

# Phase 5 Plan 2: Sync Facade -- SyncAvailabilityEngine Summary

**Shipped the thin `SyncAvailabilityEngine` background-thread bridge (D-04) so the consumer's synchronous `AvailabilityPort` can call this engine inline from its own already-running event loop, without hitting `asyncio.run()`'s running-loop crash -- proven by a real loop-in-loop regression test, not just reasoned about.**

## Performance

- **Duration:** 20 min
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- `src/availability_engine/sync.py` ships `SyncAvailabilityEngine`: one persistent background-thread event loop per instance, every one of the engine's 6 public methods (`define_resource`, `get_availability`, `place_hold`, `confirm_hold`, `release_hold`, `cancel_booking`) dispatched via `asyncio.run_coroutine_threadsafe(coro, self._loop).result()` -- never `asyncio.run()` anywhere in the module
- A `threading.Event`-gated startup handshake closes the race where a caller could invoke a method before the background loop exists
- `close()` stops the loop (`call_soon_threadsafe(loop.stop)`) and joins the thread with a 5s bounded timeout; the thread is also `daemon=True` so a consumer that never calls `close()` doesn't block process exit
- `SyncAvailabilityEngine` re-exported from `availability_engine.__init__` alongside `AvailabilityEngine`, both now part of the consumer-visible surface
- `tests/test_sync_facade.py` proves four behaviors: a plain synchronous call sequence returns real results (Test A), `close()` actually stops the thread (Test B), a naive datetime still raises the async engine's own `ValueError` (Test C), and -- the load-bearing proof -- an `async def caller()` driven by an outer `asyncio.run()` can call a sync-facade method inline without raising `RuntimeError: asyncio.run() cannot be called from a running event loop` (Test D, RESEARCH.md Pitfall 3)

## Task Commits

Each task was committed atomically, with an explicit RED/GREEN split for Task 1's TDD flow:

1. **Task 1 RED:** `75e9af3` (test) -- Tests A/B/C added; fails at collection since `availability_engine.sync` doesn't exist yet
2. **Task 1 GREEN:** `e5fa869` (feat) -- `SyncAvailabilityEngine` implemented, re-exported from `__init__.py`; Tests A/B/C pass
3. **Task 2:** `923420a` (test) -- Test D (loop-in-loop regression proof) added; passes immediately since Task 1's implementation already used the correct `run_coroutine_threadsafe` pattern (see TDD Gate Compliance below)

## Files Created/Modified
- `src/availability_engine/sync.py` - `SyncAvailabilityEngine`: background-thread bridge, generic `_call[_T]` dispatcher, `close()`
- `src/availability_engine/__init__.py` - added `SyncAvailabilityEngine` import + `__all__` entry
- `tests/test_sync_facade.py` - Tests A-D (call sequence, thread cleanup, boundary validation, loop-in-loop proof)

## Decisions Made
- Typed `_call` as `Coroutine[Any, Any, _T] -> _T` (a `TypeVar`) rather than `Any -> Any` -- every public method's return type (`AvailabilityResult`, `Hold`, `Booking`, `None`) stays `mypy --strict` clean without a `cast()` at each call site (the RESEARCH.md reference implementation used bare `Any`; tightened here because this repo enforces `--strict`)
- Followed the plan's explicit design exactly: `threading.Event` startup gate, `asyncio.new_event_loop()` + dedicated daemon thread, `run_coroutine_threadsafe` dispatch, zero exception translation, `close()` with a 5s join timeout

## TDD Gate Compliance

Task 1 followed the full RED -> GREEN cycle: `75e9af3` (test, fails at collection) -> `e5fa869` (feat, tests pass). Task 2's action was purely to extend the test file with a regression proof of behavior Task 1's implementation already delivered correctly (the `run_coroutine_threadsafe` pattern is safe from inside a running loop by construction) -- there was no separate production-code change to gate behind a RED failure, so Task 2 is committed as a single `test(...)` commit rather than a RED/GREEN pair. This is expected, not a fail-fast violation: the fail-fast rule guards against a test passing when it should have been proving new production code; here the "new" thing being proven is that the existing implementation is correct under the harder condition, and it was.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mypy --strict `no-any-return` findings on `_call`'s three typed call sites**
- **Found during:** Task 1, running `mypy --strict` before committing
- **Issue:** `_call(self, coro: Any) -> Any` (the RESEARCH.md reference implementation's signature) made `get_availability`/`place_hold`/`confirm_hold` return `Any` instead of their declared `AvailabilityResult`/`Hold`/`Booking` types
- **Fix:** Made `_call` generic (`Coroutine[Any, Any, _T] -> _T` via `TypeVar`); no behavior change, purely a type-signature tightening
- **Files modified:** `src/availability_engine/sync.py`
- **Verification:** `uv run mypy --strict src/availability_engine/sync.py` -- clean; `uv run pytest tests/test_sync_facade.py` -- still green
- **Committed in:** `e5fa869` (Task 1 GREEN commit)

**2. [Rule 1 - Bug] Fixed mypy --strict `attr-defined` on Test D's inner `caller()`**
- **Found during:** Task 2, running `mypy --strict` before committing
- **Issue:** `async def caller() -> object` lost the `AvailabilityResult` type, so `result.available` failed strict attribute-access checking
- **Fix:** Typed `caller()` as `-> AvailabilityResult` (imported alongside `Resource` from `availability_engine.contracts`)
- **Files modified:** `tests/test_sync_facade.py`
- **Verification:** `uv run mypy --strict tests/test_sync_facade.py` -- clean; test still green
- **Committed in:** `923420a` (Task 2 commit)

---
**Total deviations:** 2 auto-fixed (both mypy --strict type tightening, no behavior change)
**Impact on plan:** Cosmetic/type-safety only -- no scope creep, no behavior change.

## Issues Encountered
None.

## User Setup Required
None -- no external service configuration required.

## Next Phase Readiness
- `SyncAvailabilityEngine` is importable, tested, and proven safe from inside a running event loop -- the example `AvailabilityPort` adapter (Pattern 3, a later 05-0x plan) can now build directly on this facade
- `tests/test_sync_facade.py` is a stable, self-contained proof point: a future adapter plan should not need to touch these four tests, only add new ones alongside them
- Full suite verified green: `uv run pytest` -- 120 passed (116 pre-existing + 4 new), `ruff check` and `mypy --strict` clean on all new/modified files

---
*Phase: 05-packaging-docs-v1-release*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created files verified present on disk; all three task commit hashes (`75e9af3`, `e5fa869`, `923420a`) verified present in git log.
