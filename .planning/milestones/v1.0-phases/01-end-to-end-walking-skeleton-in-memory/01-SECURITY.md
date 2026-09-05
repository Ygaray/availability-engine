---
phase: 01
slug: end-to-end-walking-skeleton-in-memory
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
# audited_head = git HEAD sha at audit time — freshness stamp. child-result re-checks it: if
# implementation (outside .planning) changed since this sha, the audit is stale (INC-2026-08-06-04).
audited_head: 916830246d66024f544028591eb057d9ebb630ea
created: 2026-09-04
---

# Phase 01 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| consumer code -> contracts.py boundary types | Untrusted input crosses here: `Resource` construction, `get_availability(start, end)` date-range args, `confirm_hold(hold_id, payload)`'s opaque payload | Resource config, date ranges, opaque payload dicts |
| consumer code -> pip install of pinned dependencies | Supply-chain boundary: `pydantic`, `ruff`, `mypy`, `pytest`, `pytest-asyncio` pulled from PyPI at `uv add` time | Third-party package code |
| consumer code -> confirm_hold payload | Untrusted opaque `dict` crosses this boundary and must never surface in any diagnostic output | Opaque consumer payload |
| consumer code -> storage protocol | The `StorageBackend` Protocol is the only path the engine facade uses to reach mutable state | Hold/booking state mutations |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-01-01 | Information Disclosure | `confirm_hold`'s opaque `payload` dict; `errors.py` exception messages | high | mitigate | `errors.py` exception constructors accept only `resource_id`/`hold_id` identifiers, never `payload`; no call site in `engine.py`/`storage/memory.py` passes payload to any log/exception. Verified via `test_confirm_hold_payload_roundtrip` (asserts sentinel payload absent from raised `HoldNotFoundError` string repr) and direct grep of `errors.py`/`engine.py`/`storage/memory.py` — confirmed clean at L1 grep-depth. | closed |
| T-01-02 | Tampering | `contracts.py` `UtcDatetime` boundary fields; `get_availability`/`place_hold` start/end args | high | mitigate | Pydantic `AwareDatetime` + `AfterValidator` UTC-only enforcement at `Hold`/`Booking`/`Slot` fields; `place_hold` additionally rejects naive input via internal `Hold` model construction. `get_availability` initially had NO runtime enforcement (bare type-hint only) — this was caught by phase verification (Success Criterion #5 / GRID-04 gap), fixed in commit `c48d7de` by calling `time.require_utc(start)`/`time.require_utc(end)` at the top of `get_availability()`, and independently re-verified (regression test `test_get_availability_rejects_naive_datetime` exercises the facade call path directly). Status: closed. | closed |
| T-01-03 | Tampering / Denial of Service | `Resource` contract fields (`capacity`, `operating_hours`, `timezone`, `slot_duration`, `buffer`) | medium | mitigate | `Field(ge=1)` on `capacity`; `field_validator` IANA check via `zoneinfo.ZoneInfo` on `timezone`. Code review additionally found `slot_duration`/`buffer` had no positivity constraint, permitting an infinite loop / hang (DoS) in `grid_slots()` — fixed in commit `990d877` (Pydantic constraints `slot_duration > 0`, `buffer >= 0`), verified present in `contracts.py`. | closed |
| T-01-04 | Information Disclosure | Pydantic `ValidationError` messages returned to the caller | low | accept | The error surfaces only the caller's own rejected input value, never internal engine state — accepted as the intended validation-boundary behavior GRID-04/MODEL-04 require. Below `workflow.security_block_on: high` threshold; non-blocking regardless. | open — below `high` threshold (non-blocking) |
| T-01-05 | Repudiation / Elevation of Privilege (capacity bypass) | `InMemoryStore.place_hold`'s capacity check | high | mitigate | `test_place_hold_capacity_exhausted` proves a capacity-1 resource's second concurrent-slot hold is rejected with `CapacityExhaustedError`. Code review additionally found the caller-supplied capacity snapshot could race a concurrent `define_resource` capacity change — fixed in commit `dae04b1` (`place_hold` re-reads authoritative capacity from the store under its own lock before checking), verified present in `storage/memory.py`. | closed |
| T-01-SC | Tampering (supply chain) | pip installs: `pydantic`, `ruff`, `mypy`, `pytest`, `pytest-asyncio` | high | mitigate | All five ran through the package-legitimacy gate (RESEARCH.md Package Legitimacy Audit) and are pre-approved in `.planning/APPROVED-DEPS.md`. | closed |

*Status: open · closed · open — below `high` threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `workflow.security_block_on` (`high`) count toward `threats_open`*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-01-04 | Pydantic `ValidationError` messages echo only the caller's own rejected input, never internal engine state; this is required behavior for GRID-04/MODEL-04 boundary rejection, not a leak. Severity `low`, below the `high` block threshold. | secure-phase (auto) | 2026-09-04 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-04 | 6 | 5 | 1 (below threshold) | secure-phase (L1 grep-depth, ASVS 1, register authored at plan time) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-04
