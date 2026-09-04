---
phase: 05-packaging-docs-v1-release
plan: 01
subsystem: infra
tags: [hatchling, wheel-packaging, alembic, importlib-resources, uv]

# Dependency graph
requires:
  - phase: 04-sql-backend-concurrency-proof
    provides: repo-root alembic/ migration tree (env.py, script.py.mako, versions/0001_initial_schema.py) that this plan force-includes into the wheel
provides:
  - "pyproject.toml force-include mapping alembic.ini + alembic/ into availability_engine/_migrations/ inside the built wheel"
  - "src/availability_engine/py.typed (PEP 561 marker)"
  - "src/availability_engine/migrations.py::get_script_location() -- installed-wheel-first, repo-checkout-fallback Alembic script_location resolver"
  - "tests/packaging/ integration suite: build+venv+install+migrate round trip, and a wheel namelist regression guard including the examples/-exclusion prohibition"
affects: [05-02, 05-03, packaging, release]

# Actuals (#2632)
actuals:
  tokens: 2249
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "force-include (hatchling) to pull build-tooling files that live outside src/ into an importable in-package anchor at build time only"
    - "importlib.resources.files(...).joinpath(...).is_dir() dual-layout resolution: installed-wheel path first, repo-checkout fallback second"

key-files:
  created:
    - src/availability_engine/py.typed
    - src/availability_engine/_migrations/__init__.py
    - src/availability_engine/migrations.py
    - tests/packaging/__init__.py
    - tests/packaging/test_bootstrap_installed_wheel.py
    - tests/packaging/test_wheel_contains_migrations.py
  modified:
    - pyproject.toml

key-decisions:
  - "Kept [tool.hatch.build.targets.wheel] packages = [\"src/availability_engine\"] unchanged; added force-include as a separate table rather than overlapping only-include/sources, per RESEARCH.md Pitfall 5"
  - "get_script_location() falls back to the repo-root alembic/ dir (not an error) when not running from an installed wheel, so this repo's own dev workflow (alembic revision --autogenerate from repo root) is unaffected"

patterns-established:
  - "Wheel-content regression guard: assert both a positive namelist inclusion (py.typed, _migrations/alembic/**) and a negative exclusion (examples/, chatbot_adapter) in the same test, so a future careless force-include/only-include edit that widens the shipped surface fails CI immediately"

requirements-completed: [PKG-01]

coverage:
  - id: D1
    description: "A fresh venv can install the built wheel via a git-tag-style pin and import availability_engine resolves from site-packages, not the repo checkout"
    requirement: "PKG-01"
    verification:
      - kind: integration
        ref: "tests/packaging/test_bootstrap_installed_wheel.py#test_migration_bootstraps_from_installed_wheel"
        status: pass
    human_judgment: false
  - id: D2
    description: "The installed wheel bootstraps a database schema via alembic upgrade head using get_script_location() against the packaged migrations, creating all four tables (resources, holds, bookings, idempotency)"
    requirement: "PKG-01"
    verification:
      - kind: integration
        ref: "tests/packaging/test_bootstrap_installed_wheel.py#test_migration_bootstraps_from_installed_wheel"
        status: pass
    human_judgment: false
  - id: D3
    description: "py.typed ships inside the built wheel (PEP 561)"
    requirement: "PKG-01"
    verification:
      - kind: integration
        ref: "tests/packaging/test_wheel_contains_migrations.py#test_built_wheel_contains_migrations"
        status: pass
    human_judgment: false
  - id: D4
    description: "The built wheel never ships examples/ or any file naming chatbot_adapter -- structurally cannot smuggle in a dependency on the consumer"
    requirement: "PKG-01"
    verification:
      - kind: integration
        ref: "tests/packaging/test_wheel_contains_migrations.py#test_built_wheel_contains_migrations"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-09-04
status: complete
---

# Phase 5 Plan 1: Force-Include Alembic Migrations Into the Wheel Summary

**Fixed the confirmed D-05 packaging bug: the wheel now ships Alembic migrations via a hatchling `force-include`, proven by a real `uv build` → fresh venv → `pip install` → `alembic upgrade head` round trip that creates all four tables.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-09-04T20:19:45Z
- **Completed:** 2026-09-04T20:39:45Z
- **Tasks:** 2
- **Files modified:** 7 (6 created, 1 modified)

## Accomplishments
- `pyproject.toml` gained a `[tool.hatch.build.targets.wheel.force-include]` table mapping the repo-root `alembic.ini`/`alembic/` tree into an importable `availability_engine/_migrations/` anchor inside the built wheel, leaving the existing `packages` declaration untouched
- `src/availability_engine/migrations.py::get_script_location()` gives a consumer (and this repo's own tests) one function that resolves the right Alembic `script_location` in both the installed-wheel and repo-checkout cases, via `importlib.resources`
- `src/availability_engine/py.typed` closes the PEP 561 gap — a consumer's own `mypy`/type checker now trusts `availability_engine`'s inline types
- Two real (not mocked) integration tests in `tests/packaging/` prove the fix: an actual wheel build + fresh venv + install + migrate round trip, and a wheel namelist assertion (including a negative-case regression guard against ever shipping `examples/` or the future `chatbot_adapter.py`)

## Task Commits

Each task was committed atomically:

1. **Task 1: Force-include Alembic migrations into an importable wheel anchor, proven by a real build+install+migrate round trip (D-05)** - `1161b98` (feat)
2. **Task 2: Wheel namelist regression guard, including the examples/-exclusion prohibition** - `8d91fd2` (test)

_Note: Task 2's commit also carries a small ruff line-length fixup to Task 1's already-committed test file (see Deviations below)._

## Files Created/Modified
- `pyproject.toml` - added `[tool.hatch.build.targets.wheel.force-include]` table
- `src/availability_engine/py.typed` - empty PEP 561 marker file
- `src/availability_engine/_migrations/__init__.py` - near-empty docstring-only `importlib.resources` anchor
- `src/availability_engine/migrations.py` - `get_script_location()` dual-layout resolver
- `tests/packaging/__init__.py` - empty, matches existing `tests/core/`/`tests/storage/` convention
- `tests/packaging/test_bootstrap_installed_wheel.py` - build+venv+install+migrate integration proof
- `tests/packaging/test_wheel_contains_migrations.py` - wheel namelist regression guard

## Decisions Made
- Followed the plan's explicit instruction to leave `packages = ["src/availability_engine"]` unchanged and add only a separate `force-include` table — avoids the documented `only-include`/`sources` path-collision pitfall (RESEARCH.md Pitfall 5)
- `get_script_location()`'s repo-checkout fallback (rather than raising) keeps this repo's own `alembic revision --autogenerate` dev workflow working unchanged

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ruff E501 line-length findings**
- **Found during:** Task 2 (linting `tests/packaging/` before commit)
- **Issue:** Three lines exceeded the project's 88-char limit — two in `test_bootstrap_installed_wheel.py` (already committed in Task 1) and one in the new `test_wheel_contains_migrations.py`
- **Fix:** Reflowed the offending `pytest.mark.skipif(...)`, `def _run(...)` signature, and one assertion across multiple lines; no behavior change
- **Files modified:** `tests/packaging/test_bootstrap_installed_wheel.py`, `tests/packaging/test_wheel_contains_migrations.py`
- **Verification:** `uv run ruff check tests/packaging/` — all checks passed; `uv run pytest tests/packaging/ -x` — both tests still green
- **Committed in:** `8d91fd2` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug/lint)
**Impact on plan:** Cosmetic only — no scope creep, no behavior change.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PKG-01's packaging correctness is now proven and regression-guarded; subsequent 05-0x plans (sync facade, example adapter, conformance suite, README, tag cut) can build on a wheel that is confirmed installable and schema-bootstrappable
- `tests/packaging/test_wheel_contains_migrations.py`'s negative assertions (no `examples/`, no `chatbot_adapter`) are already in place and will fail loudly the moment a later plan's `examples/chatbot_adapter.py` accidentally gets force-included — no follow-up action needed, just don't touch this test's assertions when adding that file
- Full suite verified green: `uv run pytest` — 116 passed (114 pre-existing + 2 new), `ruff check` and `mypy --strict` clean on all new/modified files

---
*Phase: 05-packaging-docs-v1-release*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created files verified present on disk; both task commit hashes (`1161b98`, `8d91fd2`) verified present in git log.
