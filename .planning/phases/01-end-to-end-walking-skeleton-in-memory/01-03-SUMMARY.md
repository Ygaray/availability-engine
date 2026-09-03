---
phase: 01-end-to-end-walking-skeleton-in-memory
plan: 03
subsystem: testing
tags: [pytest, pytest-asyncio, protocol-conformance, storage-contract-suite]

# Dependency graph
requires:
  - phase: 01-end-to-end-walking-skeleton-in-memory (Plan 01-01)
    provides: AvailabilityEngine facade, InMemoryStore, StorageBackend Protocol, errors.py, contracts.py
provides:
  - StorageBackend structural-conformance test proving InMemoryStore satisfies the runtime_checkable Protocol (STORE-01)
  - Shared, parametrized storage-backend contract suite (tests/storage/contract_suite.py) ready for Phase 4 to extend with SQLStore by adding one entry to its parametrize list, no test-body rewrites (STORE-02)
  - Capacity-exhaustion rejection test proving a capacity-1 resource's second concurrent hold on the same slot raises CapacityExhaustedError (HOLD-01)
  - Payload-security regression test proving confirm_hold's payload round-trips exactly and never leaks into an exception message (HOLD-03, T-01-01)
  - Idempotent-release test proving release_hold is a no-op on an already-released hold id (HOLD-04)
affects: [04-sql-storage-backend]

# Actuals (#2632)
actuals:
  tokens: 1777
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared parametrized contract-suite class (tests/storage/contract_suite.py) as the single extension point for future storage backends — Phase 4 adds SQLStore to one parametrize list, never rewrites a test body"
    - "pytest python_files pattern extended to include contract_suite.py so a plain `uv run pytest` invocation actually collects the shared suite, not just an explicit-path invocation"

key-files:
  created:
    - tests/storage/__init__.py
    - tests/storage/test_protocol_conformance.py
    - tests/storage/contract_suite.py
  modified:
    - tests/test_engine.py
    - pyproject.toml

key-decisions:
  - "Named the contract-suite class TestStorageContractSuite (not the plan's example name StorageContractSuite) so pytest's default python_classes='Test*' pattern actually collects it — an unprefixed class name would silently produce zero collected tests"
  - "Extended pyproject.toml's [tool.pytest.ini_options] python_files to include contract_suite.py — without this, a plain `uv run pytest` at repo root never executes the shared contract suite at all (confirmed empirically: 6 tests ran, not 9, before the fix), defeating STORE-02's entire purpose of being extended and exercised by Phase 4's CI"

patterns-established:
  - "Contract-suite skeleton pattern: a shared test class in a non-test_-prefixed file (contract_suite.py), parametrized over backend factories, discoverable via an explicit pytest config addition — the pattern Phase 4 follows verbatim when adding SQLStore"

requirements-completed: [STORE-01, STORE-02, HOLD-01, HOLD-03, HOLD-04]

coverage:
  - id: D1
    description: "InMemoryStore structurally satisfies the StorageBackend Protocol (runtime-checkable isinstance check)"
    requirement: "STORE-01"
    verification:
      - kind: unit
        ref: "tests/storage/test_protocol_conformance.py#test_inmemory_satisfies_protocol"
        status: pass
    human_judgment: false
  - id: D2
    description: "Shared, parametrized storage-backend contract suite exists (save/get roundtrip, unknown-id returns None, placed hold visible via get_active_entries), parametrized over [InMemoryStore] only, extensible for Phase 4's SQLStore"
    requirement: "STORE-02"
    verification:
      - kind: unit
        ref: "tests/storage/contract_suite.py#TestStorageContractSuite::test_save_and_get_resource_roundtrip"
        status: pass
      - kind: unit
        ref: "tests/storage/contract_suite.py#TestStorageContractSuite::test_get_resource_unknown_returns_none"
        status: pass
      - kind: unit
        ref: "tests/storage/contract_suite.py#TestStorageContractSuite::test_placed_hold_appears_in_active_entries"
        status: pass
    human_judgment: false
  - id: D3
    description: "place_hold rejects with CapacityExhaustedError when a capacity-1 resource's slot already has an active hold"
    requirement: "HOLD-01"
    verification:
      - kind: unit
        ref: "tests/test_engine.py#test_place_hold_capacity_exhausted"
        status: pass
    human_judgment: false
  - id: D4
    description: "confirm_hold's payload round-trips exactly, and no exception raised along any hold/confirm/release path ever embeds the payload's contents in its message"
    requirement: "HOLD-03"
    verification:
      - kind: unit
        ref: "tests/test_engine.py#test_confirm_hold_payload_roundtrip"
        status: pass
    human_judgment: false
  - id: D5
    description: "release_hold is idempotent — releasing an already-released hold id does not raise, and frees capacity for a fresh hold"
    requirement: "HOLD-04"
    verification:
      - kind: unit
        ref: "tests/test_engine.py#test_release_hold_frees_capacity"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-09-03
status: complete
---

# Phase 01 Plan 03: Storage Conformance + Hold-Lifecycle Rejection Tests Summary

**Proved InMemoryStore's structural Protocol conformance, stood up Phase 4's SQLStore-ready parametrized contract suite, and added three engine tests proving capacity exhaustion rejection, opaque-payload non-leakage, and idempotent release — all against Plan 01-01's existing implementation, zero production code changes.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-09-03T21:16:00Z (approx, worktree spawn)
- **Completed:** 2026-09-03T21:41:00Z (approx)
- **Tasks:** 2
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments
- `tests/storage/test_protocol_conformance.py`: `isinstance(InMemoryStore(), StorageBackend)` proves structural `@runtime_checkable` conformance (STORE-01)
- `tests/storage/contract_suite.py`: shared `TestStorageContractSuite` class, `@pytest.mark.parametrize("backend_factory", [InMemoryStore], ids=["in-memory"])`, covering save/get resource roundtrip, unknown-id `None` return, and hold visibility via `get_active_entries` (STORE-02) — Phase 4 extends this by adding `SQLStore` to the one parametrize list
- `tests/test_engine.py`: three new tests — capacity-exhaustion rejection (HOLD-01), payload round-trip + non-leakage into `HoldNotFoundError`'s message (HOLD-03, T-01-01), and idempotent `release_hold` (HOLD-04)
- All 9 tests in the repo pass (`uv run pytest -q`), `ruff check` clean on all new lines, `mypy --strict` clean (untouched `src/`)

## Task Commits

Each task was committed atomically:

1. **Task 1: StorageBackend conformance test + shared parametrized contract suite skeleton** - `faac99f` (test)
2. **Task 2: Capacity-exhaustion rejection, payload-security, and idempotent-release tests** - `0db1b23` (test)

**Plan metadata:** (this commit, docs)

_Note: TDD gate compliance discussion below — see "TDD Gate Compliance" section._

## Files Created/Modified
- `tests/storage/__init__.py` - empty package marker
- `tests/storage/test_protocol_conformance.py` - `test_inmemory_satisfies_protocol`, proves STORE-01
- `tests/storage/contract_suite.py` - `TestStorageContractSuite`, the shared parametrized contract suite for STORE-02
- `tests/test_engine.py` - appended `test_place_hold_capacity_exhausted`, `test_confirm_hold_payload_roundtrip`, `test_release_hold_frees_capacity`
- `pyproject.toml` - extended `[tool.pytest.ini_options] python_files` to include `contract_suite.py` (Rule 2 deviation, see below)

## Decisions Made
- Named the shared suite class `TestStorageContractSuite` (matching pytest's default `python_classes = Test*` pattern) rather than the plan's illustrative `StorageContractSuite` name, so the class is actually collected by pytest — an unprefixed name would silently yield zero test runs from that class.
- Used a fixed, arbitrary UTC `Interval` (`2026-09-07 15:00-15:30 UTC`) for the `test_placed_hold_appears_in_active_entries` contract test rather than deriving it from `sample_resource`'s operating hours — `InMemoryStore.place_hold`/`get_active_entries` operate on raw UTC intervals with no operating-hours awareness, so any well-formed `Interval` exercises the contract correctly.

## TDD Gate Compliance

Both tasks carry `tdd="true"`, but this plan's tests prove *already-implemented* Plan 01-01 behavior rather than drive new behavior — there is no production code to make green. Every test in this plan passed on its first run (confirmed via `uv run pytest`), so a literal RED phase (an intentionally-failing test) never occurred, and no `feat(...)` GREEN commit exists. This is expected and correct for a conformance/regression-proving plan: the fail-fast rule ("if a test passes unexpectedly during RED, investigate") does not apply here because the plan's explicit purpose (per its `<objective>`) is "tests and one test-infra skeleton only — no production code changes." Both commits are `test(...)` commits; no `feat(...)`/`refactor(...)` commits were needed or created.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added `contract_suite.py` to pytest's `python_files` discovery pattern**
- **Found during:** Task 1 (StorageBackend conformance test + shared parametrized contract suite skeleton)
- **Issue:** `contract_suite.py` deliberately doesn't match pytest's default `test_*.py` / `*_test.py` collection pattern (it's a shared, imported suite, not a standalone entry point — matching the plan's explicit filename). Confirmed empirically: before the fix, a plain `uv run pytest` at repo root collected only 6 tests (missing all 3 contract-suite tests); the shared suite was completely invisible to normal CI/dev test runs, silently defeating STORE-02's stated purpose of being extended and re-run by Phase 4.
- **Fix:** Added `python_files = ["test_*.py", "*_test.py", "contract_suite.py"]` to `[tool.pytest.ini_options]` in `pyproject.toml`, with an inline comment explaining why.
- **Files modified:** `pyproject.toml`
- **Verification:** `uv run pytest -q` (default discovery, no path args) now collects and passes all 9 tests, up from 6 before the fix; `uv run pytest tests/storage/ -x -q` now shows 4 passed (was 1 before the fix).
- **Committed in:** `faac99f` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical functionality)
**Impact on plan:** Necessary for the contract suite to actually deliver on STORE-02's purpose (Phase 4 extensibility via normal CI, not hand-typed pytest invocations). No scope creep — pyproject.toml is test infrastructure, not `src/`.

## Issues Encountered
None beyond the deviation documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- STORE-01/STORE-02/HOLD-01/HOLD-03/HOLD-04 are all proven by passing automated tests, closing the coverage gaps the Plan 01-01 tracer's single happy path left open.
- `tests/storage/contract_suite.py`'s `TestStorageContractSuite` is the concrete extension point Phase 4 (SQL storage backend) will use: add `SQLStore` to the one `parametrize` list, no test-body changes.
- No blockers for the next wave/plan in this phase.

---
*Phase: 01-end-to-end-walking-skeleton-in-memory*
*Completed: 2026-09-03*

## Self-Check: PASSED

All 6 claimed files verified present on disk (`tests/storage/__init__.py`, `tests/storage/test_protocol_conformance.py`, `tests/storage/contract_suite.py`, `tests/test_engine.py`, `pyproject.toml`, this SUMMARY). Both task commits (`faac99f`, `0db1b23`) verified present in `git log`.
