---
phase: 03-idempotency-cancellation
fixed_at: 2026-09-04T17:59:30Z
review_path: .planning/phases/03-idempotency-cancellation/03-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-09-04T17:59:30Z
**Source review:** .planning/phases/03-idempotency-cancellation/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (1 critical, 4 warnings, 2 info — `fix_scope: all`)
- Fixed: 7
- Skipped: 0

All fixes were made in an isolated git worktree (`.claude/worktrees/rf-03-*`, branch
`gsd-reviewfix/03-*`), each committed atomically, then fast-forwarded onto `master`.
Verification (syntax check + full `uv run pytest tests/ -x -q`) ran in that same worktree
after `uv sync` installed its own `.venv` there; the full suite (69 tests after the new
coverage below, up from the 58 baseline) passed after every commit.

## Fixed Issues

### CR-01: Idempotency cache returns stale/phantom results after the underlying Hold or Booking changes state

**Files modified:** `src/availability_engine/storage/memory.py`, `tests/storage/contract_suite.py`
**Commit:** `be57c26`
**Applied fix:** `place_hold`'s idempotent-replay path now re-validates the cached `Hold`
against live `self._holds` state before returning it — if the referenced Hold is gone
(confirmed/released) or expired, it falls through to the real check-and-write instead of
returning a phantom result: this either creates a fresh Hold (capacity now free) or correctly
raises `CapacityExhaustedError` (capacity still occupied by the resulting Booking), both of
which reflect live state honestly. `confirm_hold`'s idempotent-replay path now always returns
`self._bookings.get(existing.result.id, existing.result)` — the live Booking record — instead
of the frozen snapshot, so a subsequently-cancelled booking is correctly reported as cancelled
on replay.

Added storage-level (`contract_suite.py`) test coverage for every previously-untested scenario
the review named: `test_place_hold_idempotent_replay_after_release_creates_fresh_hold_at_storage_level`,
`test_place_hold_idempotent_replay_after_expiry_creates_fresh_hold_at_storage_level`,
`test_place_hold_idempotent_replay_after_confirm_raises_capacity_exhausted_at_storage_level`,
`test_confirm_hold_idempotent_replay_after_cancel_reflects_live_status_at_storage_level`. This
commit also folds in the WR-01 storage-level test additions the review requested for the same
file (see WR-01 below — bundled here rather than split into a separate commit, since they touch
the identical file/region and the fix instructions explicitly asked for test coverage to land
alongside CR-01's fix).

### WR-01: No test coverage for `confirm_hold` idempotency conflict, and no storage-level (contract-suite) coverage for `confirm_hold` idempotency at all

**Files modified:** `tests/storage/contract_suite.py` (bundled in commit `be57c26`), `tests/test_engine.py` (bundled in commit `ac3e66a`)
**Commit:** `be57c26` (storage-level tests), `ac3e66a` (engine-level test)
**Applied fix:** Added all four storage-level tests the review named to `contract_suite.py`:
`test_place_hold_idempotency_conflict_at_storage_level`,
`test_confirm_hold_idempotent_replay_at_storage_level`,
`test_confirm_hold_idempotency_conflict_at_storage_level`,
`test_confirm_hold_idempotent_replay_after_hold_already_deleted_at_storage_level` (the last one
explicitly asserts `hold.id not in backend._holds` before the second call, to prove the
check-before-lookup ordering rather than silently overlapping with the plain replay test).
Added the missing engine-level `test_confirm_hold_idempotency_conflict` to `test_engine.py`,
mirroring the existing `test_place_hold_idempotency_conflict`. These landed in the CR-01 and
WR-02 commits respectively (same files edited in the same pass) rather than a standalone WR-01
commit — noted here so the mapping from finding to commit is traceable.

### WR-02: `_fingerprint`'s `default=str` fallback is not guaranteed deterministic for arbitrary payload values

**Files modified:** `src/availability_engine/storage/memory.py`, `tests/test_engine.py`
**Commit:** `ac3e66a`
**Applied fix:** `confirm_hold` now validates the payload is JSON-serializable
(`json.dumps(payload, sort_keys=True)`) before computing its fingerprint, raising a clear
`TypeError` up front for non-JSON-serializable payload values instead of silently falling back
to `_fingerprint`'s `default=str`, which is not guaranteed to be a pure function of the
payload's logical value. `place_hold`'s fingerprint is unaffected (its `default=str` usage is
solely for `datetime` slot boundaries, which are deterministic). Added
`test_confirm_hold_idempotency_payload_must_be_json_serializable` (a `set`-valued payload
field raises `TypeError`) plus the `test_confirm_hold_idempotency_conflict` test noted under
WR-01.

### WR-03: `ReasonCode` is not re-exported from the top-level package

**Files modified:** `src/availability_engine/__init__.py`, `tests/test_errors.py`
**Commit:** `e65bc8a`
**Applied fix:** Added `ReasonCode` to `__init__.py`'s import block and `__all__` list. Added
`test_reason_code_importable_from_top_level_package`, mirroring the existing
`test_new_error_names_importable_from_top_level_package` guard for `BookingStatus`.

### WR-04: `place_hold`'s `payload` parameter is accepted but silently discarded

**Files modified:** `src/availability_engine/storage/memory.py`
**Commit:** `812f9c3`
**Applied fix:** Added an explicit comment directly on `InMemoryStore.place_hold` stating the
`payload` parameter is currently a no-op (accepted only to match the `StorageBackend`
Protocol's reserved-kwarg signature), matching the existing Protocol-level comment. Did not
remove the parameter — that would diverge from the Protocol signature it implements.

### IN-01: `IdempotencyRecord`/`_idempotency` dict grows unbounded with no eviction

**Files modified:** `src/availability_engine/storage/memory.py`
**Commit:** `395bd90`
**Applied fix:** Added a comment at the `_idempotency` field declaration documenting that
records are never evicted (no TTL/cap/cleanup), and that the future SQL backend (Phase 4) will
need an explicit retention policy for the equivalent table. No behavior change, per the
review's own recommendation ("No action required for this phase").

### IN-02: Defensive `assert isinstance(...)` on idempotency replay paths silently no-ops under `-O`

**Files modified:** `src/availability_engine/storage/memory.py`
**Commit:** `c4eba44`
**Applied fix:** Replaced both `assert isinstance(existing.result, Hold)` and
`assert isinstance(existing.result, Booking)` with explicit `if not isinstance(...): raise
TypeError(...)` guards that survive `python -O`. This was applied first, ahead of CR-01, since
CR-01's staleness-revalidation logic touches the exact same code block and builds on top of the
now-explicit type guard.

## Skipped Issues

None — all 7 in-scope findings were fixed.

---

_Fixed: 2026-09-04T17:59:30Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
