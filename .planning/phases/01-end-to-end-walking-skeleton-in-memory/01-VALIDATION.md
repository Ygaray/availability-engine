---
phase: 1
slug: end-to-end-walking-skeleton-in-memory
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-03
validated: 2026-09-04
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"` in `pyproject.toml`) |
| **Config file** | `pyproject.toml`'s `[tool.pytest.ini_options]` block (created Wave 0; extended in Plan 01-03 to include `contract_suite.py` in `python_files`) |
| **Quick run command** | `uv run pytest tests/ -x -q` |
| **Full suite command** | `uv run pytest -q` (22 tests) |
| **Actual runtime** | ~0.06s (pure in-memory, no I/O) |
| **Lint/type gate** | `uv run ruff check src/ tests/` + `uv run mypy --strict src/` — both clean |

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
| 01-01-T1 | 01-01 | 1 | — | — | Canary — pytest-asyncio 1.4.0 `asyncio_mode=auto` works | n/a | `uv run pytest tests/ -k canary -x -q` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | MODEL-01 | T-01-03 | Resource rejects capacity < 1 | unit | `uv run pytest tests/test_contracts.py::test_resource_capacity_ge_1 -x` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | MODEL-02 | — | Resource accepts per-weekday list-of-intervals hours | unit | `uv run pytest tests/test_contracts.py::test_resource_operating_hours_shape -x` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | MODEL-03 | — | Resource buffer field present and applied in grid generation | unit | `uv run pytest tests/core/test_grid.py::test_buffer_applied -x` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | MODEL-04 | T-01-03 | Resource rejects non-IANA timezone string | unit | `uv run pytest tests/test_contracts.py::test_resource_timezone_validation -x` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | MODEL-05 | — | Interval/Slot/Hold immutable, half-open `[start, end)` | unit | `uv run pytest tests/core/test_intervals.py::test_frozen_and_half_open -x` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | GRID-01 | T-01-03 | Grid generation from hours+slot_length+buffer produces expected slots; non-positive `slot_duration`/`buffer` rejected (fix `990d877`) | unit | `uv run pytest tests/core/test_grid.py::test_grid_slots_basic -x` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | GRID-04 | T-01-02 | Naive datetime input raises `ValueError`/`ValidationError` at every public boundary — including the `get_availability()` facade call path (gap closed in `c48d7de`, not just the `Hold` model field) | unit | `uv run pytest tests/test_contracts.py::test_naive_datetime_rejected tests/test_engine.py::test_get_availability_rejects_naive_datetime -x` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | AVAIL-01 | — | `get_availability()` returns structured available/booked slots | integration | `uv run pytest tests/test_engine.py::test_get_availability_end_to_end -x` | ✅ | ✅ green |
| 01-03-T1 | 01-03 | 2 | STORE-01 | — | `StorageBackend` Protocol satisfied structurally by `InMemoryStore` | unit | `uv run pytest tests/storage/test_protocol_conformance.py::test_inmemory_satisfies_protocol -x` | ✅ | ✅ green |
| 01-03-T1 | 01-03 | 2 | STORE-02 | — | Shared parametrized storage-backend contract suite (ready for Phase 4's `SQLStore`) | unit | `uv run pytest tests/storage/contract_suite.py -x` | ✅ | ✅ green |
| 01-01-T1 / 01-03-T2 | 01-01 / 01-03 | 1 / 2 | HOLD-01 | T-01-05 | `place_hold` rejects when capacity exhausted; authoritative capacity re-read under lock (fix `dae04b1`) | unit | `uv run pytest tests/test_engine.py::test_place_hold_capacity_exhausted -x` | ✅ | ✅ green |
| 01-01-T1 / 01-03-T2 | 01-01 / 01-03 | 1 / 2 | HOLD-03 | T-01-01 | `confirm_hold` round-trips opaque payload untouched, never logged/reflected in exceptions | unit | `uv run pytest tests/test_engine.py::test_confirm_hold_payload_roundtrip -x` | ✅ | ✅ green |
| 01-01-T1 | 01-01 | 1 | HOLD-04 | — | `release_hold` frees capacity immediately, is idempotent | unit | `uv run pytest tests/test_engine.py::test_release_hold_frees_capacity -x` | ✅ | ✅ green |
| 01-01-T2 | 01-01 | 1 | D-05 (tooling gate) | — | `ruff` + `mypy --strict` clean on `src/` | lint/type | `uv run ruff check src/ tests/ && uv run mypy --strict src/` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Post-execution additions beyond the plan-time draft** (code-review-fix + verification-gap-closure, all covered by the tests above): `WR-01` (slot_end<=slot_start rejection, `0585f3f`), `WR-02` (`ResourceNotFoundError` unification, `8b93899`), `IN-01`/`IN-02`/`IN-03` (typing/docstring/re-export cleanups). None of these introduced a new requirement ID — they are correctness fixes within the existing MODEL/GRID/HOLD requirement set, exercised by the full 22-test suite.

---

## Wave 0 Requirements

- [x] `pyproject.toml` — `[project]` + `[tool.hatch.build]` scaffolding + `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`
- [x] `uv add --dev pytest==9.1.1 pytest-asyncio==1.4.0 ruff==0.16.6 mypy==2.3.1` — installed as planned
- [x] `tests/conftest.py` — shared fixtures (`InMemoryStore` fixture, sample `Resource` fixture)
- [x] `tests/storage/contract_suite.py` — shared parametrized storage-backend contract suite, parametrized over `[InMemoryStore]` (Phase 4 adds `SQLStore` by extending the parametrize list, no test-body rewrites)
- [x] Canary test: `test_canary` passes under `pytest.mark.asyncio` — confirmed `asyncio_mode = "auto"` works

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification. This is a pure library with no UI, network, or external-service surface; every success criterion is exercisable via pytest. Confirmed post-execution: zero gaps found in the Nyquist coverage audit — every requirement ID and every code-review/verification fix has a named, passing, automated test.*

---

## Validation Audit 2026-09-04

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

All 13 requirement-ID test commands listed in the plan-time draft were independently re-run against the post-fix codebase (commit `f2778fc` and earlier) and confirmed passing. Full suite: `uv run pytest -q` → 22 passed. `uv run ruff check src/ tests/` → clean. `uv run mypy --strict src/` → clean on 12 files.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` — finalizer's gap analysis found zero gaps

**Approval:** verified 2026-09-04
