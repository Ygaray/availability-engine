---
phase: 02
slug: capacity-time-correctness
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
audited_head: c90258bce55ce932fa5f9ff7acddce63d34ce996
created: 2026-09-04
---

# Phase 02 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Consumer -> `Resource.operating_hours` | A resource-defining caller supplies `LocalInterval` boundary times that flow into `time.py`'s local-to-UTC conversion; no validation rejects a boundary landing inside a DST gap/ambiguous hour (PEP 495 behavior). | Resource configuration data (not per-request user input) |
| (internal) `storage/memory.py` `_holds`/`_bookings` dicts | No new external input crosses a boundary Phase 1 did not already expose; internal storage-layer computation only. | Hold/booking records already validated at `engine.py` boundary |
| Consumer -> `engine.place_hold` | `slot_start`/`slot_end` are now also checked against the resource's declared operating hours (new validation added this phase). | Requested slot window (datetimes) |
| `engine` -> Consumer | `AvailabilityResult` and raised exceptions (with `.reason_code`) cross back out to the caller — the frozen public contract surface this phase restructures. | Availability/capacity data, machine-readable reason codes |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-02-01 | Tampering | `time.py::localize_operating_hours` | low | accept | A resource-definer supplying `LocalInterval` boundaries landing inside a DST gap/ambiguous hour gets Python's default deterministic `fold=0` behavior. This is resource-owner configuration data, not attacker input; `tests/core/test_grid_dst.py` and `tests/test_time_boundary.py` fixture-prove the behavior is deterministic and documented (D-01). No code change beyond documentation warranted. | closed |
| T-02-02 | Denial of Service | `storage/memory.py` `_holds`/`_bookings` dicts | medium | accept | Expired holds are excluded from active-entries counting but their records are never deleted, so unbounded hold placement in a long-running process could grow memory unboundedly. Accepted per the project's explicit "no background sweeper — lazy-on-read only" locked decision (REQUIREMENTS.md Out of Scope — a library must not own a runtime lifecycle). Deferred to a future milestone if operationally relevant. | closed |
| T-02-03 | Information Disclosure | `storage/memory.py::get_active_entries` timing | low | accept | Collapsing the previously-duplicated scan into one shared primitive introduces no new externally-observable timing channel beyond what Phase 1 already had — single-process, in-memory library, no network boundary. Not re-evaluated until Phase 4's SQL backend introduces real cross-process timing. | closed |
| T-02-04 | Tampering / Improper Input Handling (ASVS V5) | `engine.py::place_hold` | medium | mitigate | Phase 1 never validated a requested hold falls within the resource's declared operating hours. Mitigated by the new `OutsideHoursError` containment check in `place_hold` (`src/availability_engine/engine.py:109`), reusing `time_boundary.localize_operating_hours`. Verified present in code and covered by `tests/test_engine.py::test_place_hold_outside_hours` and the CR-01 follow-up regression test `test_place_hold_succeeds_after_midnight_on_overnight_hours_resource` (added during code review to close a related overnight-hours false-rejection gap in this same check). Full suite green (46/46). | closed |
| T-02-05 | Information Disclosure (ASVS V7) | `errors.py` `ReasonCode` — `HoldExpiredError` vs `HoldNotFoundError` | medium | accept | Distinguishable reason codes for an expired vs. never-existed hold create a hold-existence enumeration oracle. Accepted: HOLD-08 explicitly requires both as distinct, machine-readable codes; the downstream consumer's own not-yet-built adapter is the intended place to collapse this distinction, not this engine. Canon-referral disposition tracked in the STRIDE register per plan 02-03. | closed |
| T-02-06 | Tampering (contract drift) | `contracts.py` `AvailabilityResult` schema | low | mitigate | An unreviewed future change to the frozen public contract could silently leak a new field or alter shape without consumer awareness. Mitigated by the committed golden-file JSON-schema snapshot (`tests/golden/availability_result.schema.json`) and `tests/test_contract_conformance.py`, which fails loudly on any drift. Verified present and passing (`uv run pytest tests/test_contract_conformance.py` — 1 passed). | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-02-01 | T-02-01 | DST gap/ambiguous-hour resource configuration uses Python's deterministic `fold=0` default rather than rejection; resource-owner data, not attacker input; fixture-tested. | Phase 2 plan 02-01 (locked decision D-01) | 2026-09-04 |
| AR-02-02 | T-02-02 | Unbounded `_holds`/`_bookings` growth without a background sweeper is an explicit locked project decision (no runtime lifecycle ownership by the library); lazy-on-read expiry only. | Phase 2 plan 02-02 | 2026-09-04 |
| AR-02-03 | T-02-03 | No new timing side-channel introduced beyond Phase 1's existing single-process, in-memory design; no network boundary yet. | Phase 2 plan 02-02 | 2026-09-04 |
| AR-02-04 | T-02-05 | Hold-existence enumeration via distinct expired/not-found reason codes is required by HOLD-08; collapsing the distinction is the downstream consumer's responsibility, not this engine's. | Phase 2 plan 02-03 | 2026-09-04 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-04 | 6 | 6 | 0 | GSD orchestrator (L1 grep-depth verification, ASVS level 1, register authored at plan time — short-circuit per secure-phase.md Step 3) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-04
