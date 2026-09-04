---
phase: 03
slug: idempotency-cancellation
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
# audited_head = git HEAD sha at audit time — freshness stamp. child-result re-checks it: if
# implementation (outside .planning) changed since this sha, the audit is stale (INC-2026-08-06-04).
audited_head: 8cd264c68fae1a0acaae984043c6a65a698294b1
created: 2026-09-04
---

# Phase 03 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Consumer -> `engine.cancel_booking` | `booking_id` is caller-supplied; must resolve unambiguously to a stored, still-confirmed `Booking` or raise — never silently mutate the wrong record or no-op. | `booking_id: str` |
| `storage/memory.py` (internal) -> Consumer | `BookingNotFoundError` crosses back out to the caller; must never carry the booking's opaque payload contents. | Exception w/ `booking_id` only |
| Consumer -> `engine.place_hold`/`confirm_hold` | `idempotency_key` is an opaque, caller-supplied string; treated as untrusted data — never parsed, executed, or used to construct a path/query/format string. | `idempotency_key: str \| None` |
| `storage/memory.py` fingerprint computation (internal only) | The SHA-256 fingerprint hash derived from call args (`place_hold`) or `(hold_id, payload)` (`confirm_hold`) never crosses back out to the caller. | Internal hash only |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-03-01 | Tampering | `storage/memory.py::cancel_booking` | medium | mitigate | Explicit `.get()` + status check + raise `BookingNotFoundError` inside the existing `asyncio.Lock` — never a pop-and-ignore no-op. | closed |
| T-03-02 | Information Disclosure (ASVS V7) | `errors.py::BookingNotFoundError` | low | mitigate | Constructor accepts only `booking_id: str` — never payload/args. | closed |
| T-03-03 | Tampering (capacity-count integrity) | `storage/memory.py::get_active_entries` | medium | mitigate | `continue` branch skips entries where `booking.status == BookingStatus.CANCELLED`. | closed |
| T-03-04 | Tampering (TOCTOU) | `storage/memory.py::place_hold`/`confirm_hold` | high | mitigate | Idempotency check-execute-store sequence runs inside one uninterrupted `async with self._lock:` block; CR-01's live-state revalidation stays inside the same lock. | closed |
| T-03-05 | Denial of Service | `storage/memory.py::_idempotency` dict | medium | accept | Unbounded idempotency-record growth accepted for the dev/test in-memory backend (D-03) — no reaper by design (would violate the project's lazy-on-read-only rule); SQL retention/cleanup deferred to Phase 4. | open — below `block_on: high` threshold (non-blocking) |
| T-03-06 | Information Disclosure | `errors.py::IdempotencyConflictError` | low | mitigate | Constructor accepts only `(operation_type: str, key: str)` — never conflicting call args, payload, or the fingerprint hash. | closed |
| T-03-07 | Tampering (failure caching) | `storage/memory.py::place_hold`/`confirm_hold` | medium | mitigate | `IdempotencyRecord` written only on the success path, strictly after `Hold`/`Booking` creation — never on `CapacityExhaustedError`/`HoldExpiredError`/`HoldNotFoundError` paths, including CR-01's stale-record fallback-through path. | closed |

*Status: open · closed · open — below `high` threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (`high`) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-03-01 | T-03-05 | Unbounded `InMemoryStore._idempotency` dict growth (no TTL/cap/eviction) is an explicitly accepted risk for the dev/test in-memory backend per D-03 — a background sweeper/reaper would violate this project's locked "no background sweeper / lazy-on-read only" design rule. The SQL backend's retention/cleanup policy is deferred to Phase 4, where a real persistence layer can bound growth (e.g. TTL column + index). | gsd-security-auditor (auto-mode, `/gsd-secure-phase 03 --auto`) | 2026-09-04 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-04 | 7 | 6 | 1 (non-blocking) | gsd-security-auditor |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-04
