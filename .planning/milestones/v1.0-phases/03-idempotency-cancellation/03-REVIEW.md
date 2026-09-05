---
phase: 03-idempotency-cancellation
reviewed: 2026-09-04T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - src/availability_engine/contracts.py
  - src/availability_engine/engine.py
  - src/availability_engine/errors.py
  - src/availability_engine/__init__.py
  - src/availability_engine/storage/memory.py
  - src/availability_engine/storage/protocol.py
  - tests/storage/contract_suite.py
  - tests/test_engine.py
  - tests/test_errors.py
findings:
  critical: 1
  warning: 4
  info: 2
  total: 7
status: resolved
---

# Phase 03: Code Review Report

**Reviewed:** 2026-09-04T00:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed the `cancel_booking`/`BookingStatus` addition (Plan 03-01) and the idempotency-key
support for `place_hold`/`confirm_hold` (Plan 03-02) in `InMemoryStore`. The lock-guarded
critical section itself is sound: the idempotency check-and-write happens inside one
`async with self._lock:` block, `get_active_entries()` contains no internal `await`
suspension point (so awaiting it from inside the lock does not reopen a TOCTOU window), and
capacity-exhausted / hold-not-found / hold-expired failure paths correctly avoid caching an
`IdempotencyRecord`. The `CANCELLED`-skip branch in `get_active_entries` is correct, and no
exception constructor accepts or stores payload/booking-payload data.

The one significant gap: **cached idempotency records are never invalidated when the
referenced `Hold`/`Booking` transitions state afterward** (release, expiry, confirm, or
cancel). This produces a "phantom" replay result that is stale or permanently unusable — see
CR-01 below. There are also real test-coverage gaps for the newly-added `confirm_hold`
idempotency-conflict path, and a payload-fingerprinting fragility for non-JSON-native payload
values.

## Critical Issues

### CR-01: Idempotency cache returns stale/phantom results after the underlying Hold or Booking changes state

**File:** `src/availability_engine/storage/memory.py:116-124` (place_hold) and `:174-182` (confirm_hold)

**Issue:** `IdempotencyRecord` is written once (on first success) and then returned verbatim
on every subsequent replay with a matching `(operation_type, key)` + fingerprint — with no
check that the referenced `Hold`/`Booking` is still in the state it was in when cached:

- **`place_hold`:** if the original `Hold` is later consumed (`confirm_hold`), explicitly
  released (`release_hold`), or simply expires, a replay of `place_hold` with the same
  `idempotency_key` still returns the *original* `Hold` object — which no longer exists in
  `self._holds`. The caller receives what looks like a valid hold (with a plausible
  `expires_at`), but any subsequent `confirm_hold(hold.id, ...)` call will raise
  `HoldNotFoundError` (not `HoldExpiredError` — actively misleading). Worse: because no *new*
  `Hold` is ever created on this code path, that idempotency key can **never again produce a
  usable hold for that slot** — the freed capacity is unreachable through this key, forever
  (idempotency records never expire or get swept). This is a real, provable availability bug,
  not just a cosmetic one.
- **`confirm_hold`:** if the resulting `Booking` is later cancelled via `cancel_booking`, a
  replay of `confirm_hold` with the same `idempotency_key` still returns the cached `Booking`
  with `status=BookingStatus.CONFIRMED` — even though the live record in `self._bookings` now
  has `status=BookingStatus.CANCELLED`. A consumer retrying the original confirm request would
  be told the booking is confirmed when it has actually been cancelled.

Neither scenario is covered by any test (`tests/test_engine.py`,
`tests/storage/contract_suite.py`) — there is no test exercising
place_hold-idempotent-replay-after-release/expiry/confirm, or
confirm_hold-idempotent-replay-after-cancel.

**Fix:** On a cache hit, re-validate that the cached result still reflects live state before
returning it:
```python
if existing is not None:
    if existing.fingerprint == fp:
        # Re-validate live state instead of trusting the frozen snapshot.
        if isinstance(existing.result, Hold):
            live = self._holds.get(existing.result.id)
            if live is None or live.expires_at <= datetime.now(UTC):
                # stale — fall through to re-run the real check-and-write below
                # (and drop/replace the stale record on success)
                ...
            else:
                return live
        else:  # Booking
            live = self._bookings.get(existing.result.id, existing.result)
            return live  # always return current live state, not the stale snapshot
    raise IdempotencyConflictError(...)
```
At minimum, `confirm_hold`'s replay should return `self._bookings[existing.result.id]` (the
live record) rather than the frozen snapshot, and `place_hold`'s replay should verify the
cached `Hold.id` is still present and unexpired in `self._holds` before returning it,
otherwise treat the record as stale and fall through to re-run capacity check + creation.

## Warnings

### WR-01: No test coverage for `confirm_hold` idempotency conflict, and no storage-level (contract-suite) coverage for `confirm_hold` idempotency at all

**File:** `tests/storage/contract_suite.py` (whole file); `tests/test_engine.py:404-432`

**Issue:** `test_place_hold_idempotency_conflict` exercises `IdempotencyConflictError` for
`place_hold`, but there is no equivalent `test_confirm_hold_idempotency_conflict` (same
`idempotency_key`, different `payload`). More importantly, `tests/storage/contract_suite.py`
— the shared, backend-agnostic suite explicitly designed so "Phase 4 adds SQLStore to the
single `parametrize` list ... without rewriting any test body" — only tests
`place_hold`'s idempotent replay (`test_place_hold_idempotent_replay_at_storage_level`). It
has **no** storage-level test for `place_hold` idempotency conflict, nor for `confirm_hold`
idempotent replay or conflict at all. A future SQL backend could get `confirm_hold`
idempotency (or the replay-ordering requirement — "this check must come BEFORE the
`hold is None` lookup") completely wrong and the shared contract suite would not catch it.

**Fix:** Add to `contract_suite.py`:
- `test_place_hold_idempotency_conflict_at_storage_level`
- `test_confirm_hold_idempotent_replay_at_storage_level`
- `test_confirm_hold_idempotency_conflict_at_storage_level`
- `test_confirm_hold_idempotent_replay_after_hold_already_deleted_at_storage_level` (the
  scenario the in-code comment on `memory.py:169-173` explicitly calls out as the reason for
  the check ordering, but which is never actually exercised end-to-end by a test with a
  *second* call after the hold is gone).

### WR-02: `_fingerprint`'s `default=str` fallback is not guaranteed deterministic for arbitrary payload values

**File:** `src/availability_engine/storage/memory.py:28-34`, used at `:176`

**Issue:** `confirm_hold`'s fingerprint is `_fingerprint(hold_id, payload)` where `payload:
dict[str, Any]` is caller-supplied and, per `Booking.payload: dict[str, Any]` in
`contracts.py`, is not constrained to JSON-native types. `json.dumps(..., default=str)` falls
back to `str(obj)` for anything not natively JSON-serializable. For a `set`, a custom class
without a stable `__str__`/`__repr__` (default object repr embeds the memory address), or any
object whose `str()` is not a pure function of its logical value, two calls with a
*logically identical* payload can produce **different** fingerprints. That causes a
legitimate retry to be misclassified as a conflicting request and raise a spurious
`IdempotencyConflictError`, rather than replaying the original result.

**Fix:** Either document that `payload` must be JSON-serializable with stable-value semantics
for idempotency fingerprinting to work correctly, or restrict the fingerprint to the JSON
round-trip itself (`json.dumps(payload, sort_keys=True)` without `default=str`, raising a
clear `TypeError`/`ValueError` up front for non-JSON-serializable payloads instead of silently
producing a fingerprint that may not be reproducible).

### WR-03: `ReasonCode` is not re-exported from the top-level package

**File:** `src/availability_engine/__init__.py:1-43`

**Issue:** `errors.py`'s own docstring says a consumer can "inspect `.reason_code` to branch
without string-matching the exception type," and this phase adds a new
`ReasonCode.IDEMPOTENCY_CONFLICT` value that consumers need to match against. But
`ReasonCode` itself is never imported/re-exported in `__init__.py` — a consumer must reach
into `availability_engine.contracts.ReasonCode` to get the enum type for exhaustiveness
matching or type annotations, breaking the "code against the top-level package" pattern the
rest of this file establishes (it already re-exports `BookingStatus`, `SlotStatus`, etc., for
exactly this reason — `tests/test_errors.py`'s
`test_new_error_names_importable_from_top_level_package` guards this exact class of omission
for `BookingStatus`/`BookingNotFoundError`, but no equivalent guard exists for `ReasonCode`).

**Fix:** Add `ReasonCode` to the `__init__.py` import block and `__all__` list.

### WR-04: `place_hold`'s `payload` parameter is accepted but silently discarded

**File:** `src/availability_engine/storage/memory.py:99-107`; `src/availability_engine/storage/protocol.py:22-33`

**Issue:** `InMemoryStore.place_hold` accepts a `payload: dict[str, Any] | None = None`
parameter (per the `StorageBackend` Protocol) but never references it anywhere in the method
body — it is silently dropped. A caller who passes `payload=` to `place_hold` expecting it to
carry through to the eventual `Booking` (a reasonable assumption, since `confirm_hold` takes
a `payload` that *does* get stored) would have that data vanish with no error or warning.
This predates Phase 3 but is part of the reviewed surface and remains an unaddressed
usability trap now that idempotency wiring has touched this same signature.

**Fix:** Either remove the unused `payload` parameter from `place_hold` until it has a real
use, or add a docstring/comment on `place_hold` itself (not just the Protocol) making clear it
is currently a no-op, matching the existing Protocol-level comment.

## Info

### IN-01: `IdempotencyRecord`/`_idempotency` dict grows unbounded with no eviction

**File:** `src/availability_engine/storage/memory.py:49-51`

**Issue:** Idempotency records are never removed (no TTL, no cap, no cleanup tied to the
underlying `Hold`'s expiry). Not a correctness bug for a reference in-memory store and
explicitly out of v1 performance scope, but worth a one-line note for whoever builds the SQL
backend in Phase 4, since an unbounded idempotency table has real operational implications
there.

**Fix:** No action required for this phase; consider documenting the intended
retention/cleanup policy before Phase 4's SQL backend is designed.

### IN-02: Defensive `assert isinstance(...)` on idempotency replay paths silently no-ops under `-O`

**File:** `src/availability_engine/storage/memory.py:122, 180`

**Issue:** `assert isinstance(existing.result, Hold)` / `assert isinstance(existing.result,
Booking)` are pure type-narrowing aids for mypy; under `python -O` these asserts are stripped
entirely. Since the `(operation_type, key)` tuple key genuinely prevents cross-type
collisions today, this isn't currently reachable, but if that invariant is ever weakened
(e.g., a future single-namespace idempotency scheme), returning `existing.result` typed as
`Hold` when it's actually a `Booking` would silently pass through to a caller expecting a
`Hold`, with no runtime guard once asserts are stripped.

**Fix:** No action required now; if the key-scoping invariant changes, replace the `assert`
with an explicit `if not isinstance(...): raise TypeError(...)` that survives `-O`.

---

_Reviewed: 2026-09-04T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
