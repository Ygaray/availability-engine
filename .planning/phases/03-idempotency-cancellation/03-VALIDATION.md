---
phase: 3
slug: idempotency-cancellation
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| **Estimated runtime** | ~1-2 seconds |

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
| 03-01-TBD | 01 | 0 | HOLD-07 | — | `place_hold` with same idempotency key + same args returns original `Hold`, no second capacity consumption | integration | `uv run pytest tests/test_engine.py::test_place_hold_idempotent_replay -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | 01 | 0 | HOLD-07 | — | `place_hold` with same key + materially different args raises `IdempotencyConflictError` with `.reason_code == ReasonCode.IDEMPOTENCY_CONFLICT` | integration | `uv run pytest tests/test_engine.py::test_place_hold_idempotency_conflict -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | 01 | 0 | HOLD-07 | — | `confirm_hold` same-key replay returns original `Booking` | integration | `uv run pytest tests/test_engine.py::test_confirm_hold_idempotent_replay -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | 01 | 0 | HOLD-07 | — | Idempotency check-and-write happens inside the existing lock's critical section (no TOCTOU race between two concurrent same-key retries) | contract-suite (parametrized, STORE-02/04) | `uv run pytest tests/storage/contract_suite.py -k idempot -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | 01 | 0 | HOLD-06 | — | `cancel_booking` on a confirmed booking frees capacity — freed slot reappears in `get_availability`/accepts a new `place_hold` immediately | integration | `uv run pytest tests/test_engine.py::test_cancel_booking_frees_capacity -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | 01 | 0 | HOLD-06 | — | `cancel_booking` on an unknown or already-cancelled booking raises `BookingNotFoundError` (`.reason_code == ReasonCode.NOT_FOUND`) — no silent no-op | integration | `uv run pytest tests/test_engine.py::test_cancel_booking_not_found_or_already_cancelled -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | 01 | 0 | HOLD-08 (regression) | — | New exceptions (`IdempotencyConflictError`, `BookingNotFoundError`) both carry a non-null `.reason_code`; neither constructor accepts/stores a payload argument | unit | `uv run pytest tests/test_errors.py -x` | ✅ (extend existing list) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are placeholders (`03-01-TBD`) — the planner assigns concrete task IDs; this table's Req→Test mapping is the binding contract, task-ID cells are refreshed once PLAN.md exists.*

---

## Wave 0 Requirements

- [ ] `tests/test_engine.py` — add idempotent-replay, idempotency-conflict, and cancel-booking test functions (file exists, new test functions needed)
- [ ] `tests/test_errors.py` — extend `_CONCRETE_EXCEPTION_CLASSES` with `IdempotencyConflictError` and `BookingNotFoundError`
- [ ] `tests/storage/contract_suite.py` — add idempotency and cancel_booking cases to the shared parametrized suite, so Phase 4's SQL backend addition is exercised against identical behavior from day one (STORE-04)
- [ ] No new fixture files or framework install needed — `pytest-asyncio`/`hypothesis` already present and imported by `contract_suite.py`

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

> **Plan-time state is a DRAFT.** Leave frontmatter `status: draft` and `nyquist_compliant: false`.
> These are finalized ONLY post-execution by the Nyquist finalizer (the `verify:post` →
> `validate-phase` hook, invoked by execute-phase `finalize_nyquist_validation` after Gate-1). Never
> set `nyquist_compliant: true` — or otherwise "sign off" compliance — at plan time, and do not let
> the plan-checker do so (INC-2026-07-27-01: a premature plan-time flip is what caused inconsistent
> COMPLIANT/PARTIAL milestone-audit states).

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] _(finalizer-only, post-execution)_ `nyquist_compliant` — leave `false` at plan time; the
      finalizer sets `true` iff its gap analysis finds zero gaps

**Approval:** pending — finalizer-owned, not set at plan time
