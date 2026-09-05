---
phase: 02-capacity-time-correctness
fixed_at: 2026-09-04T16:48:09Z
review_path: .planning/phases/02-capacity-time-correctness/02-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-09-04T16:48:09Z
**Source review:** .planning/phases/02-capacity-time-correctness/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5
- Fixed: 5
- Skipped: 0

## Fixed Issues

### CR-01: `OutsideHoursError` false-rejects valid holds on overnight-hours resources when the slot falls after local midnight

**Files modified:** `src/availability_engine/time.py`, `tests/test_engine.py`
**Commit:** `e051a0f`
**Applied fix:** `localize_operating_hours` now widens its calendar-date scan one day back (`start.astimezone(tz).date() - timedelta(days=1)`) so an overnight `LocalInterval` anchored on the prior day is always considered, even when the query window is narrowed to the exact requested slot (as `place_hold` does). `intersect()` already discards anything that doesn't overlap the actual query window, so this is safe. Added `test_place_hold_succeeds_after_midnight_on_overnight_hours_resource`, which mirrors the review's exact repro (Monday `22:00->06:00` resource, hold on the Tuesday `05:30-06:00` tail); confirmed the test fails on the pre-fix code (raises `OutsideHoursError`) and passes after the fix.

### CR-02: Reducing a resource's capacity while holds/bookings are active crashes `get_availability`

**Files modified:** `src/availability_engine/core/availability.py`, `tests/test_engine.py`
**Commit:** `b7391fb`
**Applied fix:** `free_fragments` now clamps `remaining` to `max(0, capacity - active_count)` instead of allowing it to go negative, so a resource whose capacity was legally reduced below its already-active hold/booking count degrades to "fully booked" (`remaining=0`) rather than crashing `get_availability` with an uncaught `pydantic.ValidationError` on `PublicSlot.remaining`'s `ge=0` constraint. Chose the clamp (fix option b) over a storage-layer capacity-decrease guard (option a) because capacity is enforced per-slot-interval overlap (not a single resource-wide count), which would make a correct storage-layer guard on `save_resource` significantly more complex than the graceful-degradation clamp for the same correctness outcome. Added `test_get_availability_survives_capacity_reduction_below_active_count`, which mirrors the review's exact repro (capacity 3 -> 1 while 3 holds are active); confirmed the test fails on the pre-fix code (raises `pydantic.ValidationError` with `remaining=-2`) and passes after the fix.

### WR-01: Overlapping `LocalInterval`s for the same weekday produce duplicate `PublicSlot`s in the two-list contract

**Files modified:** `src/availability_engine/contracts.py`, `tests/test_contracts.py`
**Commit:** `299d44b`
**Applied fix:** Added a `Resource` `model_validator(mode="after")` that rejects overlapping `LocalInterval`s declared for the same `Weekday`. Overlap is detected by normalizing each interval's occupied minutes onto a "double-day" timeline (minutes 1440-2880 represent the following calendar day), so overnight (midnight-crossing) intervals are checked correctly too, then sorting by start and checking adjacent pairs (sufficient to detect any overlap's existence once sorted by start). Adjacent, non-overlapping (touching) intervals — the split-shift shape D-03 exists to support — remain valid. Added three tests: overlapping same-day intervals rejected, overlapping overnight intervals rejected, and adjacent non-overlapping intervals still accepted.

### WR-02: Zero-length `LocalInterval` (`start == end`) silently expands to a full 24-hour window

**Files modified:** `src/availability_engine/contracts.py`, `tests/test_contracts.py`
**Commit:** `299d44b` (combined with WR-01 — both fixes touch the same `LocalInterval`/`Resource` validation surface in `contracts.py`)
**Applied fix:** Chose the review's alternative fix option: added a `field_validator` on `LocalInterval.end` that rejects `start == end` outright at construction time, rather than special-casing `end == start` inside `time.py::localize_operating_hours` to mean "no hours this day". Failing loudly at the boundary is more consistent with the codebase's existing MODEL-0x validator pattern (`capacity`, `slot_duration`, `buffer`, `timezone` are all validated the same way) and avoids adding a new silent-no-op branch to the grid-generation hot path. Added `test_local_interval_rejects_zero_length`.

### IN-01: `InMemoryStore.confirm_hold`'s expired-hold cleanup claim doesn't match its own error path

**Files modified:** `src/availability_engine/storage/memory.py`
**Commit:** `499049a`
**Applied fix:** Chose the review's first fix option: tightened the comment on `get_active_entries` to accurately state that `confirm_hold` only deletes the `_holds` record on a *successful* confirmation (one made before expiry), not on the `HoldExpiredError` path — rather than changing `confirm_hold`'s behavior to delete the record when raising `HoldExpiredError`. Preserving existing behavior (no functional change) since correctness was already unaffected per the review; this is a documentation-only fix. No new test needed (no behavior changed) — existing hold-expiry tests in `tests/test_hold_expiry.py` continue to pass unchanged.

## Skipped Issues

None — all in-scope findings were fixed.

---

**Verification (worktree `.claude/worktrees/rf-02-3331100-1788497567`, isolated per commit and after all 5 fixes):**
- `uv run pytest -q` — 46 passed (up from 40 baseline; 6 new regression tests added: 1 for CR-01, 1 for CR-02, 4 for WR-01/WR-02)
- `uv run ruff check .` — All checks passed
- `uv run mypy --strict src/` — Success: no issues found in 12 source files

_Fixed: 2026-09-04T16:48:09Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
