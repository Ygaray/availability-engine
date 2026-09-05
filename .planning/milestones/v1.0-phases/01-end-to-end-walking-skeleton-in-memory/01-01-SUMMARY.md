---
phase: 01-end-to-end-walking-skeleton-in-memory
plan: 01
subsystem: api
tags: [pydantic, asyncio, python, scheduling, protocol, in-memory-storage]

requires: []
provides:
  - "src/availability_engine/contracts.py — Pydantic v2 public boundary types (Resource with slot_duration, LocalInterval, Weekday, PublicSlot, SlotStatus, AvailabilityResult, Hold, Booking) enforcing UTC-aware datetimes"
  - "src/availability_engine/storage/protocol.py — async, coarse-grained, runtime-checkable StorageBackend Protocol"
  - "src/availability_engine/storage/memory.py — InMemoryStore reference implementation with asyncio.Lock-guarded atomic hold placement"
  - "src/availability_engine/engine.py — AvailabilityEngine facade (define_resource, get_availability, place_hold, confirm_hold, release_hold)"
  - "ruff + mypy --strict tooling gate on src/ (D-05), both exit 0"
affects: [02-timezone-dst-and-capacity-hardening, phase-3-idempotency, phase-4-sql-backend]

actuals:
  tokens: 7225
  tasks: 2
  commits: 2

tech-stack:
  added: [pydantic==2.13.5, pytest==9.1.1, pytest-asyncio==1.4.0, ruff==0.16.6, mypy==2.3.1]
  patterns:
    - "Two-tier type system: Pydantic v2 BaseModel for public boundary (contracts.py), stdlib frozen/slots dataclass for internal value objects (core/intervals.py)"
    - "zoneinfo confined to contracts.py (IANA validation) and time.py (local-to-UTC conversion); never imported inside core/"
    - "Sweep-line event-counting for capacity-aware free_fragments(), generalized to capacity >= 1 from day one"
    - "asyncio.Lock-guarded check-and-write inside one critical section (no intervening await) to close the TOCTOU window on hold placement"

key-files:
  created:
    - src/availability_engine/contracts.py
    - src/availability_engine/errors.py
    - src/availability_engine/time.py
    - src/availability_engine/core/intervals.py
    - src/availability_engine/core/grid.py
    - src/availability_engine/core/availability.py
    - src/availability_engine/storage/protocol.py
    - src/availability_engine/storage/memory.py
    - src/availability_engine/engine.py
    - tests/conftest.py
    - tests/test_engine.py
    - pyproject.toml
  modified: []

key-decisions:
  - "Resource.slot_duration: timedelta added as a required field (no default) per the plan's design note, resolving the gap between RESEARCH.md's Resource example (no slot_duration) and GRID-01's fixed-duration-grid requirement — treated as part of D-03's already-locked Resource-shape decision, not a new one-way door."
  - "SlotStatus changed from RESEARCH.md's verbatim `class SlotStatus(str, Enum)` to `class SlotStatus(StrEnum)` to satisfy ruff's UP042 (py312+ idiom) under the D-05 strict-tooling gate — identical runtime behavior (string-valued enum), so no contract change for the parallel consumer."
  - "engine.place_hold raises a plain ValueError when resource_id doesn't resolve to a stored Resource — not one of errors.py's three domain exceptions, since resource-not-found wasn't in the plan's specified error set and is a caller-programming-error case, not a runtime domain condition."

requirements-completed: [MODEL-01, MODEL-02, MODEL-03, MODEL-04, MODEL-05, GRID-01, GRID-04, AVAIL-01, STORE-01, STORE-02, HOLD-01, HOLD-03, HOLD-04]

coverage:
  - id: D1
    description: "AvailabilityEngine(InMemoryStore()) construction + define_resource() with capacity/hours/buffer/timezone/slot_duration"
    requirement: "MODEL-01"
    verification:
      - kind: integration
        ref: "tests/test_engine.py#test_get_availability_end_to_end"
        status: pass
    human_judgment: false
  - id: D2
    description: "get_availability() returns a structured AvailabilityResult with slots reflecting operating hours, slot_duration, and buffer"
    requirement: "AVAIL-01"
    verification:
      - kind: integration
        ref: "tests/test_engine.py#test_get_availability_end_to_end"
        status: pass
    human_judgment: false
  - id: D3
    description: "place_hold() succeeds on an available slot, confirm_hold() turns it into a Booking whose payload matches exactly what was passed in, release_hold() frees the slot immediately"
    requirement: "HOLD-01, HOLD-03, HOLD-04"
    verification:
      - kind: integration
        ref: "tests/test_engine.py#test_get_availability_end_to_end"
        status: pass
    human_judgment: false
  - id: D4
    description: "ruff check src/ and mypy --strict src/ both exit 0 (D-05 tooling gate)"
    requirement: "STORE-02"
    verification:
      - kind: other
        ref: "uv run ruff check src/ && uv run mypy --strict src/"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-09-03
status: complete
---

# Phase 1 Plan 1: End-to-End Walking Skeleton Summary

**A real AvailabilityEngine over InMemoryStore — define resource, sweep-line free-fragment computation, fixed-duration grid, and atomic hold/confirm/release — proven end to end by one integration test, with ruff/mypy --strict clean on src/.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-09-03T21:14:13Z
- **Tasks:** 2
- **Files modified:** 18 (17 new + uv.lock)

## Accomplishments

- Pydantic v2 public boundary (`contracts.py`): `Resource` (with the plan-mandated `slot_duration` field), `LocalInterval`, `Weekday`, `PublicSlot`/`SlotStatus`, `AvailabilityResult`, `Hold`, `Booking` — every crossing datetime is UTC-enforced via `UtcDatetime`
- Internal interval math (`core/intervals.py`, `core/grid.py`, `core/availability.py`): half-open `Interval` dataclass, buffer-aware fixed-duration grid generation, and sweep-line capacity-aware `free_fragments()`
- UTC boundary (`time.py`): `localize_operating_hours()` converting per-weekday local hours to UTC, clipped to the query window; same-day-only scope (midnight-crossing/DST deferred to Phase 2)
- Async `StorageBackend` Protocol + `InMemoryStore` reference implementation with lock-guarded atomic hold placement (closes the TOCTOU window)
- `AvailabilityEngine` facade wiring `define_resource -> get_availability -> place_hold -> confirm_hold -> release_hold`
- One passing end-to-end integration test (`test_get_availability_end_to_end`) plus a pytest-asyncio canary
- `ruff` + `mypy --strict` enforced on `src/`, both exit 0

## Task Commits

1. **Task 1: End-to-end walking skeleton — resource, grid, availability, hold/confirm/release** - `54dbdaa` (feat)
2. **Task 2: Enforce ruff + mypy --strict tooling on src/ (D-05)** - `9a0692b` (chore)

## Files Created/Modified

- `pyproject.toml` - uv + hatchling scaffold, pinned deps, `[tool.pytest.ini_options]`, `[tool.ruff]`, `[tool.mypy]`
- `src/availability_engine/contracts.py` - public boundary types
- `src/availability_engine/errors.py` - `CapacityExhaustedError`, `HoldExpiredError`, `HoldNotFoundError`
- `src/availability_engine/time.py` - UTC guard + local-hours-to-UTC conversion
- `src/availability_engine/core/intervals.py` - half-open `Interval` + overlap/intersect
- `src/availability_engine/core/grid.py` - fixed-duration slot grid with buffer
- `src/availability_engine/core/availability.py` - sweep-line `free_fragments()`
- `src/availability_engine/storage/protocol.py` - `StorageBackend` Protocol
- `src/availability_engine/storage/memory.py` - `InMemoryStore`
- `src/availability_engine/engine.py` - `AvailabilityEngine` facade
- `tests/conftest.py` - `store`/`sample_resource` fixtures
- `tests/test_engine.py` - canary + end-to-end integration test
- `.gitignore`, `.python-version`, `uv.lock` - project hygiene/reproducibility (added, not in plan's `files_modified` list, but required to make `uv sync`/`uv run` reproducible and keep build artifacts out of git)

## Decisions Made

- `Resource.slot_duration: timedelta` added as a required field, per the plan's own design note (D-03 extension, no new checkpoint needed — first authoring of the `Resource` contract, no consumer pinned yet).
- `SlotStatus(StrEnum)` instead of RESEARCH.md's verbatim `SlotStatus(str, Enum)`, to satisfy ruff's `UP042` under the D-05 strict-tooling gate. Identical runtime/serialization behavior — no impact on the frozen public contract shape.
- `place_hold()` raises `ValueError` for an unknown `resource_id` (not one of the three domain exceptions in `errors.py`), since this case wasn't specified in the plan's error set and represents a caller-programming error, not a runtime domain condition like capacity exhaustion or hold expiry.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added `.gitignore` for build/venv/cache artifacts**
- **Found during:** Task 1 (project scaffolding)
- **Issue:** No `.gitignore` existed; `.venv/`, `__pycache__/`, `.pytest_cache/` etc. would otherwise risk being committed
- **Fix:** Added a standard Python `.gitignore` (`.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.egg-info/`, `dist/`, `build/`)
- **Files modified:** `.gitignore`
- **Verification:** `git status --short` shows no generated artifacts as untracked
- **Committed in:** `54dbdaa` (Task 1 commit)

**2. [Rule 3 - Blocking] Pinned Python to 3.12 via `.python-version`**
- **Found during:** Task 1 (first `uv sync`)
- **Issue:** `uv sync` without a pinned interpreter selected the newest available CPython (3.13.13) instead of the project's locked 3.12+ baseline, risking a mismatch with `[tool.mypy] python_version = "3.12"`
- **Fix:** Added `.python-version` pinning `3.12`; re-synced against the system's `/usr/bin/python3.12` (3.12.3)
- **Files modified:** `.python-version`, `uv.lock` (regenerated)
- **Verification:** `uv run pytest` reports `platform linux -- Python 3.12.3`
- **Committed in:** `54dbdaa` (Task 1 commit)

**3. [Rule 1 - Bug] Fixed 8 ruff/mypy violations surfaced by Task 2's strict gate**
- **Found during:** Task 2 (ruff + mypy --strict enforcement)
- **Issue:** Import ordering, `datetime.timezone.utc` vs. `datetime.UTC` alias (`UP017`), `zip()` vs. `itertools.pairwise()` (`RUF007`), bare `dict` generics (`mypy [type-arg]`), `SlotStatus(str, Enum)` vs. `StrEnum` (`UP042`), and several lines exceeding the 88-char default under the newly-enabled `E` ruleset
- **Fix:** `ruff check --fix` for auto-fixable items; manually replaced `zip()` with `itertools.pairwise()`, added `dict[str, Any]` type args across `contracts.py`/`storage/protocol.py`/`storage/memory.py`/`engine.py`, switched `SlotStatus` to `StrEnum`, and wrapped long lines
- **Files modified:** `contracts.py`, `core/availability.py`, `engine.py`, `storage/memory.py`, `storage/protocol.py`, `time.py`
- **Verification:** `uv run ruff check src/` and `uv run mypy --strict src/` both exit 0; `uv run pytest tests/` still 2/2 passing after each fix
- **Committed in:** `9a0692b` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (1 missing critical, 1 blocking, 1 bug-class tooling fixups)
**Impact on plan:** All auto-fixes were hygiene/tooling-correctness items required to make the D-05 gate genuinely pass, or reproducibility fixes with zero effect on the frozen public contract. No scope creep.

## Issues Encountered

- RESEARCH.md's Pattern 1 shows `from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict` composed as `Annotated[AwareDatetime, AfterValidator(_require_utc)]` per its own comment; implemented exactly as documented (`UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]`).
- No mypy 2.3.1-vs-1.13.x version-behavior surprise was encountered — every `mypy --strict` finding was a standard `[type-arg]` (bare generic) violation, present across mypy major versions. Documented per D-05's instruction to record this explicitly rather than silently disable `strict = true`.
- The tracer feedback gate (per `execute-plan.md`'s tracer execution flow) was evaluated after Task 1's commit: `workflow.auto_advance` and `workflow._auto_chain_active` are both false/absent in this project's config, but `workflow.human_verify_mode = "end-of-phase"` is set — per #3309, this project's config already opts out of mid-flight `checkpoint:human-verify` halts in favor of end-of-phase batching. Since Task 1's `<verify>` is a pure automated `pytest` command (no UI/URL for a human to visit) and it was re-confirmed passing before proceeding, execution continued directly to Task 2 rather than emitting a mid-flight checkpoint.

## User Setup Required

None - no external service configuration required. `uv sync` installs everything needed; no API keys, no environment variables.

## Next Phase Readiness

- The frozen public contract (`Resource` with `slot_duration`, `PublicSlot`/`SlotStatus`, `AvailabilityResult`, `Hold`, `Booking`) and `StorageBackend`/`AvailabilityEngine` signatures are now real, importable code the parallel consumer (SocialNetwork-Chatbot) can pin against.
- Phase 2 (timezone/DST + capacity-K hardening) can build directly on `time.py`'s `localize_operating_hours()` and `core/availability.py`'s `free_fragments()` — both are explicitly scoped in this phase to same-day/capacity>=1 cases, with the sweep-line primitive's *shape* already correct for extension.
- No blockers. `01-02-PLAN.md` and `01-03-PLAN.md` (if any further Phase 1 plans exist) can proceed.

---
*Phase: 01-end-to-end-walking-skeleton-in-memory*
*Completed: 2026-09-03*

## Self-Check: PASSED

All 12 claimed key-files verified present on disk. Both task commits (`54dbdaa`, `9a0692b`) verified present in `git log`.
