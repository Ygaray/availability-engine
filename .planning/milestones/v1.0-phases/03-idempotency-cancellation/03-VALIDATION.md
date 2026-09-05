---
phase: 3
slug: idempotency-cancellation
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-04
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) — unchanged from Phases 1-2 |
| **Config file** | `pyproject.toml`'s existing `[tool.pytest.ini_options]` block — no changes needed |
| **Quick run command** | `uv run pytest tests/test_engine.py tests/test_errors.py -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~0.4 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_engine.py tests/test_errors.py -x -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-02-Task1 | 02 | 2 | HOLD-07 | T-03-04 | `place_hold` with same idempotency key + same args returns original `Hold`, no second capacity consumption | integration | `uv run pytest tests/test_engine.py::test_place_hold_idempotent_replay -x` | ✅ | ✅ green |
| 03-02-Task1 | 02 | 2 | HOLD-07 | T-03-06 | `place_hold` with same key + materially different args raises `IdempotencyConflictError` with `.reason_code == ReasonCode.IDEMPOTENCY_CONFLICT` | integration | `uv run pytest tests/test_engine.py::test_place_hold_idempotency_conflict -x` | ✅ | ✅ green |
| 03-02-Task2 | 02 | 2 | HOLD-07 | T-03-04 | `confirm_hold` same-key replay returns original `Booking` | integration | `uv run pytest tests/test_engine.py::test_confirm_hold_idempotent_replay -x` | ✅ | ✅ green |
| 03-02-Task1/2 | 02 | 2 | HOLD-07 | T-03-04 / T-03-07 | Idempotency check-and-write happens inside the existing lock's critical section (no TOCTOU race between two concurrent same-key retries); CR-01 fix adds replay-after-release/expiry/confirm/cancel staleness coverage at the storage-contract level | contract-suite (parametrized, STORE-02/04) | `uv run pytest tests/storage/contract_suite.py -k idempot -x` (9 tests) | ✅ | ✅ green |
| 03-01-Task1 | 01 | 1 | HOLD-06 | T-03-03 | `cancel_booking` on a confirmed booking frees capacity — freed slot reappears in `get_availability`/accepts a new `place_hold` immediately | integration | `uv run pytest tests/test_engine.py::test_cancel_booking_frees_capacity -x` | ✅ | ✅ green |
| 03-01-Task2 | 01 | 1 | HOLD-06 | T-03-01 | `cancel_booking` on an unknown or already-cancelled booking raises `BookingNotFoundError` (`.reason_code == ReasonCode.NOT_FOUND`) — no silent no-op | integration | `uv run pytest tests/test_engine.py::test_cancel_booking_not_found_or_already_cancelled -x` | ✅ | ✅ green |
| 03-01-Task2 | 01 | 1 | HOLD-06 (regression) | — | New exceptions (`IdempotencyConflictError`, `BookingNotFoundError`) both carry a non-null `.reason_code`; neither constructor accepts/stores a payload argument; both are importable from the top-level package | unit | `uv run pytest tests/test_errors.py -x` (3 tests) | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_engine.py` — idempotent-replay, idempotency-conflict, cancel-booking, and CR-01 staleness-replay test functions added
- [x] `tests/test_errors.py` — `_CONCRETE_EXCEPTION_CLASSES` extended with `IdempotencyConflictError` and `BookingNotFoundError` (7 total classes)
- [x] `tests/storage/contract_suite.py` — idempotency and cancel_booking cases added to the shared parametrized suite (9 idempotency-related cases), exercising Phase 4's future SQL backend against identical behavior from day one (STORE-04)
- [x] No new fixture files or framework install needed — `pytest-asyncio` already present

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

Post-execution gap analysis (finalizer, `/gsd-execute-phase 03 --auto`'s `finalize_nyquist_gate` step)
found **zero gaps**: every requirement-to-task mapping in the Per-Task Verification Map above has a
passing automated test, independently re-run at finalization time (`uv run pytest tests/ -q` → 69
passed). This includes the code-review-driven CR-01 fix's dedicated regression tests (replay after
release/expiry/confirm/cancel), which were added after this file's plan-time draft and are now
reflected in the contract-suite row's test count (9, up from the plan-time-estimated 4).

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none remained — all were filled during execution)
- [x] No watch-mode flags
- [x] Feedback latency < 15s (actual: ~0.4s full suite)
- [x] _(finalizer-only, post-execution)_ `nyquist_compliant: true` — gap analysis found zero gaps

**Approval:** verified 2026-09-04
