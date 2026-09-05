---
phase: 03-idempotency-cancellation
plan: 02
subsystem: api
tags: [idempotency, asyncio, storage-protocol, hashlib, concurrency]

# Dependency graph
requires:
  - phase: 03-idempotency-cancellation
    provides: "Plan 03-01's six-file vertical slice (cancel_booking, BookingStatus, BookingNotFoundError) proving the facade -> storage-protocol -> InMemoryStore wiring pattern this plan reuses for idempotency"
provides:
  - IdempotencyConflictError exception (reason_code = ReasonCode.IDEMPOTENCY_CONFLICT)
  - IdempotencyRecord frozen/slotted dataclass and _fingerprint SHA-256 helper (storage/memory.py, internal only)
  - InMemoryStore._idempotency dict keyed (operation_type, key), checked/written inside the existing asyncio.Lock critical section for both place_hold and confirm_hold
  - AvailabilityEngine.place_hold / .confirm_hold idempotency_key: str | None = None kwarg (threaded through the already-reserved Protocol kwarg)
  - Storage-contract-suite coverage for idempotent place_hold, proving Phase 4 SQL-backend forward compatibility (STORE-04)
affects: [04-sql-backend]

actuals:
  tokens: 4341
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Idempotency lives entirely inside InMemoryStore, never at the AvailabilityEngine facade — checked and written inside the SAME async with self._lock: block already guarding place_hold/confirm_hold, with zero intervening await between check and store (closes the TOCTOU window)."
    - "Idempotency records are keyed (operation_type, key) — never a bare key string — so the identical literal key reused across place_hold and confirm_hold never collides (D-01)."
    - "A fingerprint (SHA-256 over sorted-key JSON, datetime coerced via default=str) is computed from the operation's semantically-relevant arguments only (ttl_seconds deliberately excluded from place_hold's fingerprint), and the idempotency record is written strictly on the success path, after the Hold/Booking is constructed — never on a failure path (CapacityExhaustedError/HoldExpiredError/HoldNotFoundError never gets cached)."

key-files:
  created: []
  modified:
    - src/availability_engine/errors.py
    - src/availability_engine/storage/memory.py
    - src/availability_engine/engine.py
    - src/availability_engine/__init__.py
    - tests/test_engine.py
    - tests/test_errors.py
    - tests/storage/contract_suite.py

key-decisions:
  - "confirm_hold's idempotency check runs BEFORE the hold-is-None lookup (not after) — a replay's underlying hold was already deleted by the first call's success, and checking idempotency first is what lets the replay return the original Booking instead of incorrectly raising HoldNotFoundError."
  - "ttl_seconds is excluded from place_hold's fingerprint per the plan's Open Question 1 resolution — a legitimate retry may resend a different remaining-timeout budget for the same logical request without tripping IdempotencyConflictError."

patterns-established:
  - "Idempotency-key replay pattern: look up (operation_type, key) first inside the lock; matching fingerprint returns the cached result immediately, mismatched fingerprint raises IdempotencyConflictError, and the record is only ever written after the underlying operation's own success path completes."

requirements-completed: [HOLD-07]

coverage:
  - id: D1
    description: "place_hold called twice with the identical idempotency_key and identical (resource_id, slot_start, slot_end) returns the same Hold.id both times on a capacity-1 resource; the second call never raises CapacityExhaustedError."
    requirement: "HOLD-07"
    verification:
      - kind: unit
        ref: "tests/test_engine.py#test_place_hold_idempotent_replay"
        status: pass
      - kind: unit
        ref: "tests/storage/contract_suite.py#TestStorageContractSuite::test_place_hold_idempotent_replay_at_storage_level"
        status: pass
    human_judgment: false
  - id: D2
    description: "place_hold with the same idempotency_key but a materially different resource_id/slot_start/slot_end raises IdempotencyConflictError with .reason_code == ReasonCode.IDEMPOTENCY_CONFLICT."
    requirement: "HOLD-07"
    verification:
      - kind: unit
        ref: "tests/test_engine.py#test_place_hold_idempotency_conflict"
        status: pass
    human_judgment: false
  - id: D3
    description: "Two place_hold calls sharing the same idempotency_key and identical args, issued concurrently via asyncio.gather, are serialized by InMemoryStore's single asyncio.Lock: both resolve to the same Hold.id and capacity is never double-consumed."
    requirement: "HOLD-07"
    verification:
      - kind: unit
        ref: "tests/test_engine.py#test_place_hold_concurrent_same_key_race_returns_same_hold"
        status: pass
    human_judgment: false
  - id: D4
    description: "confirm_hold's idempotency behavior mirrors place_hold's: a same-key/same-(hold_id,payload) replay returns the identical Booking without raising HoldNotFoundError, even though the underlying hold was already consumed by the first call."
    requirement: "HOLD-07"
    verification:
      - kind: unit
        ref: "tests/test_engine.py#test_confirm_hold_idempotent_replay"
        status: pass
    human_judgment: false
  - id: D5
    description: "The same literal idempotency key string used for an unrelated place_hold call and confirm_hold call never collides — each operation's idempotency record is scoped by (operation_type, key)."
    requirement: "HOLD-07"
    verification:
      - kind: unit
        ref: "tests/test_engine.py#test_idempotency_key_scoped_per_operation_type"
        status: pass
    human_judgment: false
  - id: D6
    description: "IdempotencyConflictError is exhaustively covered by the reason-code test (7 concrete exception classes total across both 03-01 and 03-02)."
    verification:
      - kind: unit
        ref: "tests/test_errors.py#test_every_exception_has_reason_code"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-09-04
status: complete
---

# Phase 03 Plan 02: Idempotent place_hold/confirm_hold Summary

**Wired `idempotency_key` end-to-end through `AvailabilityEngine.place_hold`/`confirm_hold` into `InMemoryStore`'s lock-guarded critical sections — a same-key/same-args replay returns the original `Hold`/`Booking`, a same-key/different-args replay raises `IdempotencyConflictError`, and a concurrent same-key race (proven via `asyncio.gather`) never double-consumes capacity.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-09-04T17:38:00Z
- **Completed:** 2026-09-04T17:44:23Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- `IdempotencyConflictError` in `errors.py` (`reason_code = ReasonCode.IDEMPOTENCY_CONFLICT`), constructor storing only `(operation_type, key)` — never the conflicting call args or payload, per the module's existing no-payload-in-constructor rule.
- `IdempotencyRecord` frozen/slotted dataclass and a module-level `_fingerprint(*parts)` SHA-256 helper (`hashlib` + `json.dumps(sort_keys=True, default=str)`) in `storage/memory.py`, plus a new `InMemoryStore._idempotency: dict[tuple[str, str], IdempotencyRecord]` field.
- `place_hold`'s idempotency check/store lives entirely inside the existing `async with self._lock:` block, before the capacity check, with the record written only on the success path (after the `Hold` is stored) — a `CapacityExhaustedError` is never cached, so a later retry after capacity frees up succeeds.
- `confirm_hold` mirrors the same pattern, but the idempotency check runs BEFORE the `hold is None` lookup — a replay's underlying hold may already have been deleted by the first call's success.
- `AvailabilityEngine.place_hold`/`confirm_hold` both gained a defaulted `idempotency_key: str | None = None` kwarg, forwarded unchanged into the storage layer (the `StorageBackend` Protocol signature was already frozen forward-compatibly since Phase 1 — no Protocol change needed).
- `IdempotencyConflictError` exported from the top-level `availability_engine` package (alphabetically ordered).
- Concurrency proven directly: `test_place_hold_concurrent_same_key_race_returns_same_hold` uses `asyncio.gather` to issue two same-key concurrent `place_hold` calls against a capacity-1 resource and asserts both resolve to one `Hold.id` with `remaining == 0` afterward (not two holds).
- Key-scope isolation proven: the identical literal key string used for one `place_hold` call and one unrelated `confirm_hold` call never collides (`(operation_type, key)` scoping, D-01).
- Storage-contract-suite coverage (`test_place_hold_idempotent_replay_at_storage_level`) exercises idempotent replay directly against `InMemoryStore`, positioning Phase 4's SQL backend to be proven against identical behavior without rewriting the test body (STORE-04).

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end idempotent place_hold — replay, conflict, and concurrent-race safety** - `b1f5f41` (feat, tdd tracer)
2. **Task 2: confirm_hold idempotency + key-scope isolation + contract-suite coverage** - `3e77293` (feat, tdd)

_Note: this plan's `tdd="true"` tasks land implementation + tests together per task (tracer/expand pattern), matching Plan 03-01's precedent — both commits already carried passing tests at commit time._

## Files Created/Modified
- `src/availability_engine/errors.py` - `IdempotencyConflictError`
- `src/availability_engine/storage/memory.py` - `IdempotencyRecord`, `_fingerprint`, `InMemoryStore._idempotency`, `place_hold`/`confirm_hold` idempotency check-execute-store logic inside the existing lock
- `src/availability_engine/engine.py` - `idempotency_key` kwarg on `place_hold`/`confirm_hold` facade methods
- `src/availability_engine/__init__.py` - `IdempotencyConflictError` export
- `tests/test_engine.py` - `test_place_hold_idempotent_replay`, `test_place_hold_idempotency_conflict`, `test_place_hold_concurrent_same_key_race_returns_same_hold`, `test_confirm_hold_idempotent_replay`, `test_idempotency_key_scoped_per_operation_type`
- `tests/test_errors.py` - `IdempotencyConflictError` added to `_CONCRETE_EXCEPTION_CLASSES`
- `tests/storage/contract_suite.py` - `test_place_hold_idempotent_replay_at_storage_level`

## Decisions Made
- `ttl_seconds` deliberately excluded from `place_hold`'s fingerprint (Open Question 1) — a legitimate retry may resend a different remaining-timeout budget for the same logical request without spuriously tripping `IdempotencyConflictError`.
- `confirm_hold`'s idempotency lookup runs strictly before the `hold is None` check, since the point of the replay is to succeed even after the underlying hold has already been consumed and deleted by the first call.
- Idempotency lives entirely inside `InMemoryStore` (never at the `AvailabilityEngine` facade) per the plan's explicit architecture — the facade only threads the opaque key through.

## Deviations from Plan

None - plan executed exactly as written. Both tasks' `<verify>` commands (`uv run pytest tests/test_engine.py -x -q` and `uv run pytest tests/ -x -q`) passed on the first run; `ruff check` and `mypy --strict` (project convention) were additionally run and both passed clean with no findings.

## Issues Encountered
None.

## Next Phase Readiness
- HOLD-07 fully satisfied: idempotent replay, conflict detection, and concurrent-race safety are proven end-to-end for both `place_hold` and `confirm_hold`, at both the facade and storage-contract level.
- `storage/protocol.py`'s `place_hold`/`confirm_hold` signatures remain unchanged — the `idempotency_key` kwarg was already reserved there since Phase 1, so Phase 4's SQL backend inherits the same signature with no Protocol migration needed.
- `errors.py`'s `ReasonCode` enum was not widened — `IDEMPOTENCY_CONFLICT` was already pre-seeded in Phase 2.
- No blockers for Phase 4.

---
*Phase: 03-idempotency-cancellation*
*Completed: 2026-09-04*

## Self-Check: PASSED

- FOUND: `.planning/phases/03-idempotency-cancellation/03-02-SUMMARY.md`
- FOUND: commit `b1f5f41` (Task 1)
- FOUND: commit `3e77293` (Task 2)
