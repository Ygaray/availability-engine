---
phase: 1
slug: end-to-end-walking-skeleton-in-memory
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-03
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"` in `pyproject.toml`) |
| **Config file** | none yet — Wave 0 creates `pyproject.toml`'s `[tool.pytest.ini_options]` block |
| **Quick run command** | `uv run pytest tests/ -x -q` |
| **Full suite command** | `uv run pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds (pure in-memory, no I/O) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-xx | 01 | 0 | — | — | N/A (scaffolding) | n/a | `uv run pytest tests/ -k canary -x -q` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | MODEL-01 | V5 | Resource rejects capacity < 1 | unit | `uv run pytest tests/test_contracts.py::test_resource_capacity_ge_1 -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | MODEL-02 | V5 | Resource accepts per-weekday list-of-intervals hours | unit | `uv run pytest tests/test_contracts.py::test_resource_operating_hours_shape -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | MODEL-03 | — | Resource buffer field present and applied in grid generation | unit | `uv run pytest tests/core/test_grid.py::test_buffer_applied -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | MODEL-04 | V5 | Resource rejects non-IANA timezone string | unit | `uv run pytest tests/test_contracts.py::test_resource_timezone_validation -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | MODEL-05 | — | Interval/Slot/Hold immutable, half-open `[start, end)` | unit | `uv run pytest tests/core/test_intervals.py::test_frozen_and_half_open -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | GRID-01 | — | Grid generation from hours+slot_length+buffer produces expected slots | unit | `uv run pytest tests/core/test_grid.py::test_grid_slots_basic -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | GRID-04 | V5 | Naive datetime input raises ValidationError at every public boundary type | unit | `uv run pytest tests/test_contracts.py::test_naive_datetime_rejected -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | AVAIL-01 | — | `get_availability()` returns structured available/booked slots | integration | `uv run pytest tests/test_engine.py::test_get_availability_end_to_end -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | STORE-01 | — | `StorageBackend` Protocol satisfied structurally by `InMemoryStore` | unit | `uv run pytest tests/storage/test_protocol_conformance.py::test_inmemory_satisfies_protocol -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | STORE-02 | — | `InMemoryStore` CRUD round-trips resource/hold/booking | unit | `uv run pytest tests/storage/contract_suite.py -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | HOLD-01 | — | `place_hold` rejects when capacity exhausted | unit | `uv run pytest tests/test_engine.py::test_place_hold_capacity_exhausted -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | HOLD-03 | V5 (T-01-01: opaque-payload logging) | `confirm_hold` round-trips opaque payload untouched, never logged/reflected | unit | `uv run pytest tests/test_engine.py::test_confirm_hold_payload_roundtrip -x` | ❌ W0 | ⬜ pending |
| 01-xx-xx | 01 | TBD | HOLD-04 | — | `release_hold` frees capacity immediately, is idempotent | unit | `uv run pytest tests/test_engine.py::test_release_hold_frees_capacity -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Task IDs are placeholders (`xx`) — the planner fills in exact task IDs and wave numbers when PLAN.md is written; this map's requirement coverage must not shrink.*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — `[project]` + `[tool.hatch.build]` scaffolding + `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`
- [ ] `uv add --dev pytest==9.1.1 pytest-asyncio==1.4.0 ruff==0.16.6 mypy==2.3.1` — **re-verify these exact pins against PyPI immediately before running**, per D-06 (research snapshot is from 2026-09-03; all four packages show active release cadence)
- [ ] `tests/conftest.py` — shared fixtures (`InMemoryStore` fixture, sample `Resource` fixture)
- [ ] `tests/storage/contract_suite.py` — shared parametrized storage-backend contract suite skeleton, parametrized over `[InMemoryStore]` only in Phase 1 (designed so Phase 4 adds `SQLStore` without rewriting test bodies)
- [ ] Canary test: `async def test_canary(): assert True` under `pytest.mark.asyncio` — confirms pytest-asyncio 1.4.0's `asyncio_mode = "auto"` config works (the `event_loop` fixture was removed in this major version) before any real async tests are written

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification. This is a pure library with no UI, network, or external-service surface; every success criterion is exercisable via pytest.*

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
- [ ] Feedback latency < 10s
- [ ] _(finalizer-only, post-execution)_ `nyquist_compliant` — leave `false` at plan time; the
      finalizer sets `true` iff its gap analysis finds zero gaps

**Approval:** pending — finalizer-owned, not set at plan time
