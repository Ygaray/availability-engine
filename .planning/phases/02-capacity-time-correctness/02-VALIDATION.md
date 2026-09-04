---
phase: 2
slug: capacity-time-correctness
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
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
| **Estimated runtime** | ~1 second (46 tests) |

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
| 02-01 | 01 | 1 | AVAIL-02 | — | Sweep-line remaining-capacity never negative or over-capacity across random overlapping holds | property (hypothesis) | `uv run pytest tests/core/test_availability.py -k capacity -x` | ✅ | ✅ green |
| 02-02 | 02 | 2 | AVAIL-03 | — | Expired hold excluded from `get_active_entries()` on next read, no manual release | unit | `uv run pytest tests/storage/contract_suite.py -k expired -x` | ✅ | ✅ green |
| 02-03 | 03 | 2 | AVAIL-04 | T-02-06 | `AvailabilityResult`'s JSON schema matches the committed golden file | unit | `uv run pytest tests/test_contract_conformance.py -x` | ✅ | ✅ green |
| 02-01 | 01 | 1 | GRID-02 | — | Spring-forward gap and fall-back doubled-hour produce no missing/duplicated/shifted slots on real 2026 dates | fixture-based unit | `uv run pytest tests/core/test_grid_dst.py -x` | ✅ | ✅ green |
| 02-01 | 01 | 1 | GRID-03 | — | Overnight `end<=start` LocalInterval produces correct UTC span, including across a DST date | fixture-based unit | `uv run pytest tests/test_time_boundary.py -x` | ✅ | ✅ green |
| 02-02 | 02 | 2 | HOLD-05 | T-02-02 | A hold with an elapsed TTL stops counting against capacity on the very next `place_hold`, no `release_hold` call | unit (time-machine) | `uv run pytest tests/test_hold_expiry.py -x` | ✅ | ✅ green |
| 02-03 | 03 | 2 | HOLD-08 | T-02-04, T-02-05 | `place_hold` outside operating hours raises `OutsideHoursError` with `.reason_code == ReasonCode.OUTSIDE_HOURS`; every `errors.py` exception has a non-null `.reason_code` | unit | `uv run pytest tests/test_engine.py -k outside_hours tests/test_errors.py -x` | ✅ | ✅ green |
| code-review CR-01 | 02 (fix) | post-merge | GRID-03 / HOLD-08 interaction | — | Overnight-hours `place_hold` on the after-midnight tail no longer false-rejects with `OutsideHoursError` | regression unit | `uv run pytest tests/test_engine.py -k overnight -x` | ✅ | ✅ green |
| code-review CR-02 | 02 (fix) | post-merge | AVAIL-02 | — | Reducing capacity below active-entry count clamps `remaining` to 0 instead of crashing `get_availability` | regression unit | `uv run pytest tests/core/test_availability.py -k clamp -x` | ✅ | ✅ green |
| code-review WR-01/WR-02 | 02 (fix) | post-merge | GRID-01/GRID-03 | — | `LocalInterval` construction rejects overlapping same-weekday intervals and zero-length (`start == end`) intervals | unit | `uv run pytest tests/test_contracts.py -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/core/test_availability.py` — hypothesis property tests for AVAIL-02 (plus CR-02 capacity-clamp regression test)
- [x] `tests/core/test_grid_dst.py` — real-date DST fixtures for GRID-02
- [x] `tests/test_time_boundary.py` — midnight-crossing + DST-boundary fixtures for GRID-03
- [x] `tests/test_contract_conformance.py` + `tests/golden/*.schema.json` — golden-file generation for AVAIL-04
- [x] `tests/test_errors.py` — exhaustiveness test that every concrete exception class has a `.reason_code`
- [x] Framework install: `tzdata`, `time-machine`, `hypothesis` pinned in `pyproject.toml`
- [x] Canary: `time_machine.travel(...)` confirmed compatible with `pytest-asyncio`'s `asyncio_mode="auto"` (used throughout `tests/test_hold_expiry.py`, `tests/storage/contract_suite.py`)

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Audit 2026-09-04

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

All 7 phase requirements (AVAIL-02, AVAIL-03, AVAIL-04, GRID-02, GRID-03, HOLD-05, HOLD-08) have
COVERED, green automated tests. The 3 code-review findings requiring new regression coverage
(CR-01 overnight-hours false-rejection, CR-02 capacity-reduction crash, WR-01/WR-02 LocalInterval
shape validation) each landed with their own regression tests as part of the fixer's commits,
verified independently by re-running each test file in isolation. Full suite: 46/46 passing,
`ruff check .` clean, `mypy --strict src/` clean. No manual-only items — every phase behavior is
automated.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` — finalizer's gap analysis found zero gaps

**Approval:** verified 2026-09-04
