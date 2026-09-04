---
phase: 2
slug: capacity-time-correctness
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-03
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) — unchanged from Phase 1 |
| **Config file** | `pyproject.toml`'s existing `[tool.pytest.ini_options]` block — no changes needed |
| **Quick run command** | `uv run pytest tests/ -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-TBD | 01 | 0 | AVAIL-02 | — | Sweep-line remaining-capacity never negative or over-capacity across random overlapping holds | property (hypothesis) | `uv run pytest tests/core/test_availability.py::test_free_fragments_never_exceeds_capacity -x` | ❌ W0 | ⬜ pending |
| 02-01-TBD | 01 | 0 | AVAIL-03 | — | Expired hold excluded from `get_active_entries()` on next read, no manual release | unit | `uv run pytest tests/storage/contract_suite.py -k expired -x` | ❌ W0 | ⬜ pending |
| 02-01-TBD | 01 | 0 | AVAIL-04 | — | `AvailabilityResult`'s JSON schema matches the committed golden file | unit | `uv run pytest tests/test_contract_conformance.py::test_availability_result_schema_matches_golden -x` | ❌ W0 | ⬜ pending |
| 02-01-TBD | 01 | 0 | GRID-02 | — | Spring-forward gap and fall-back doubled-hour produce no missing/duplicated/shifted slots on real 2024-2026 dates | fixture-based unit | `uv run pytest tests/core/test_grid_dst.py -x` | ❌ W0 | ⬜ pending |
| 02-01-TBD | 01 | 0 | GRID-03 | — | Overnight `end<=start` LocalInterval produces correct UTC span, including across a DST date | fixture-based unit | `uv run pytest tests/test_time_boundary.py -k midnight -x` | ❌ W0 | ⬜ pending |
| 02-01-TBD | 01 | 0 | HOLD-05 | — | A hold with an elapsed TTL stops counting against capacity on the very next `place_hold`, no `release_hold` call | unit (time-machine) | `uv run pytest tests/test_engine.py::test_expired_hold_stops_counting_against_capacity -x` | ❌ W0 | ⬜ pending |
| 02-01-TBD | 01 | 0 | HOLD-08 | T-V5 | `place_hold` outside operating hours raises `OutsideHoursError` with `.reason_code == ReasonCode.OUTSIDE_HOURS`; every `errors.py` exception has a non-null `.reason_code` | unit | `uv run pytest tests/test_engine.py::test_place_hold_outside_hours tests/test_errors.py::test_every_exception_has_reason_code -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are placeholders (`02-01-TBD`) — the planner assigns concrete task IDs; this table's Req→Test mapping is the binding contract, task-ID cells are refreshed once PLAN.md exists.*

---

## Wave 0 Requirements

- [ ] `tests/core/test_availability.py` — hypothesis property tests for AVAIL-02
- [ ] `tests/core/test_grid_dst.py` — real-date DST fixtures for GRID-02
- [ ] `tests/test_time_boundary.py` — midnight-crossing + DST-boundary fixtures for GRID-03
- [ ] `tests/test_contract_conformance.py` + `tests/golden/*.schema.json` — golden-file generation for AVAIL-04
- [ ] `tests/test_errors.py` — exhaustiveness test that every concrete exception class has a `.reason_code`
- [ ] Framework install: `uv add tzdata && uv add --dev time-machine hypothesis` — confirm exact pins still current immediately before running (PyPI publishes continuously)
- [ ] Canary: a single `time_machine.travel(...)` smoke test confirming it interacts correctly with `pytest-asyncio`'s `asyncio_mode="auto"` before writing the full HOLD-05 test

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
