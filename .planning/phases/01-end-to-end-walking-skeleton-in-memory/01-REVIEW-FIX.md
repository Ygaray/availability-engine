---
phase: 01-end-to-end-walking-skeleton-in-memory
fixed_at: 2026-09-03T22:28:25Z
review_path: .planning/phases/01-end-to-end-walking-skeleton-in-memory/01-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 7
skipped: 1
status: resolved
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-09-03T22:28:25Z
**Source review:** .planning/phases/01-end-to-end-walking-skeleton-in-memory/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (fix_scope: all)
- Fixed: 7
- Skipped: 1 (documented acceptable-skip — out of Phase 1 scope per `.planning/REQUIREMENTS.md`)

Verification: all edits applied and verified inside an isolated git worktree
(`gsd-reviewfix/01-*`, fast-forwarded into `master` on completion). Full gate
run at the end of the session, in the same worktree: `uv run pytest -q` → 21
passed; `uv run ruff check src/ tests/` → all checks passed; `uv run mypy
--strict src/` → no issues found in 12 source files.

## Fixed Issues

### CR-02: `grid_slots` infinite-loops when `slot_duration <= 0` or buffer makes the step non-positive

**Files modified:** `src/availability_engine/contracts.py`, `tests/test_contracts.py`
**Commit:** `990d877`
**Applied fix:** Added Pydantic field constraints on `Resource` — `slot_duration: Annotated[timedelta, Field(gt=timedelta(0))]` and `buffer: Annotated[timedelta, Field(ge=timedelta(0))]` — matching the review's suggested fix exactly. A positive `slot_duration` plus a non-negative `buffer` can never sum to a non-positive step, closing the DoS-hang path in `grid_slots`. Added `test_resource_slot_duration_must_be_positive` and `test_resource_buffer_cannot_be_negative` regression tests.

### WR-01: No validation that `slot_start < slot_end` on hold placement

**Files modified:** `src/availability_engine/engine.py`, `tests/test_engine.py`
**Commit:** `0585f3f`
**Applied fix:** Added an explicit `if slot_end <= slot_start: raise ValueError(...)` check in `AvailabilityEngine.place_hold` before constructing the `Interval`, per the review's first suggested option (boundary validation on the facade, easiest place to diagnose the mistake). Added `test_place_hold_rejects_inverted_or_zero_length_slot` covering both a zero-length and a fully-inverted slot.

### WR-02: Inconsistent unknown-resource handling between read and write paths, using a generic `ValueError`

**Files modified:** `src/availability_engine/errors.py`, `src/availability_engine/engine.py`, `src/availability_engine/__init__.py`, `tests/test_engine.py`
**Commit:** `8b93899`
**Applied fix:** Added `ResourceNotFoundError` to `errors.py` following the existing identifier-only pattern (`CapacityExhaustedError`/`HoldExpiredError`/`HoldNotFoundError`). `place_hold` now raises it instead of a bare `ValueError`. Per the review's "decide deliberately ... but they should match" guidance, `get_availability` was changed from silently returning an empty `AvailabilityResult` to also raising `ResourceNotFoundError`, so both facade paths fail identically and catchably for an unknown `resource_id`. Re-exported the new error from the top-level package `__init__.py` alongside its siblings. Added `test_unknown_resource_raises_consistently` covering both paths.

### WR-03: `place_hold`'s capacity snapshot is fetched outside the storage lock

**Files modified:** `src/availability_engine/storage/memory.py`, `tests/storage/contract_suite.py`
**Commit:** `dae04b1`
**Applied fix:** Implemented the review's option (a): `InMemoryStore.place_hold` now re-reads the authoritative `Resource.capacity` from its own `self._resources` store under the same lock it uses for the count-vs-capacity comparison, rather than trusting the caller-supplied `capacity` parameter. The parameter is kept (required by the frozen `StorageBackend` protocol shape) as a fallback only for the case where the resource isn't tracked by this backend, which the engine facade already guards against. This closes the race where a concurrent `define_resource` call changes capacity between the engine's read and the storage lock's acquisition, without changing the protocol's public signature (preserving forward-compat for the Phase 4 SQL backend). Added `test_place_hold_uses_authoritative_stored_capacity` to the shared parametrized contract suite (so any future backend, e.g. the Phase 4 SQL implementation, is held to the same guarantee), which passes a deliberately wrong caller-supplied `capacity=100` against a `capacity=1` resource and asserts the second hold is still rejected.

### IN-01: `CapacityExhaustedError.slot` typed as `Any` weakens the strict-typing convention

**Files modified:** `src/availability_engine/errors.py`
**Commit:** `c77117c`
**Applied fix:** Changed `slot: Any` to `slot: Interval`, importing `Interval` from `core.intervals` exactly as the review suggested. Confirmed no import cycle (`core/intervals.py` and `core/__init__.py` import nothing from `errors.py`). `mypy --strict` passes clean.

### IN-02: `free_fragments` docstring claims sweep-line counting, implementation recomputes brute-force per segment

**Files modified:** `src/availability_engine/core/availability.py`
**Commit:** `9381b83`
**Applied fix:** Chose the review's second option (update the docs rather than rewrite the algorithm, since performance was explicitly out of review scope and Phase 1's own module docstring already defers property-based capacity-K correctness work to Phase 2). Rewrote both the module docstring and the function docstring to describe what's actually implemented: boundary timestamps harvested from `busy`-interval start/end events, then `active_count` recomputed directly against `busy` per emitted segment (not an incrementally-maintained running counter).

### IN-03: `InMemoryStore` is not re-exported from `storage/__init__.py`

**Files modified:** `src/availability_engine/storage/__init__.py`
**Commit:** `d68512a`
**Applied fix:** Added `from availability_engine.storage.memory import InMemoryStore` + `__all__ = ["InMemoryStore"]` to `storage/__init__.py`, following the review's first suggested option — `InMemoryStore` is a documented, consumer-facing reference/test backend (used directly in `conftest.py`, `test_engine.py`, and the contract suite), so making it reachable at the package level is the correct discoverability fix.

## Skipped Issues

### CR-01: Expired holds are never excluded from capacity/availability — lazy-expiry design is unimplemented

**File:** `src/availability_engine/storage/memory.py:37-53` (`get_active_entries`), `:55-69` (`_count_active`), `:94-115` (`confirm_hold`)
**Reason:** Documented acceptable-skip — out of Phase 1 scope by the project's own requirement traceability. The gap this finding describes is exactly `AVAIL-03` ("Availability reads exclude expired holds ... via the one shared active-entries primitive used by every read and write path") and `HOLD-05` ("Expired holds auto-release lazily ... on the next read or hold attempt"), both of which `.planning/REQUIREMENTS.md`'s traceability table explicitly assigns to **Phase 2**, not Phase 1. Fully implementing the fix as suggested (filtering/purging expired holds across `get_active_entries`, `_count_active`, and `confirm_hold`, plus the `time-machine`-based regression test) would mean building AVAIL-03/HOLD-05's functionality itself inside Phase 1, expanding this phase's scope rather than fixing an in-phase bug. This is a real, tracked gap — not a "won't fix" — and should be picked up when Phase 2 implements AVAIL-03/HOLD-05.
**Original issue:** The lazy-expiry check (`ttl_seconds`, `Hold.expires_at`, `HoldExpiredError`) exists in Phase 1 but is only enforced in `confirm_hold`, and even there it doesn't purge the expired hold from `self._holds`. `_count_active` (used by `place_hold`) and `get_active_entries` (used by `get_availability`) never check `expires_at` at all, so an unconfirmed/unreleased hold permanently occupies capacity and permanently renders its slot `BOOKED`, forever, once its TTL elapses.

---

_Fixed: 2026-09-03T22:28:25Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
