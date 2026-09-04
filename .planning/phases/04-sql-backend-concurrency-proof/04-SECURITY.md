---
phase: 04
slug: sql-backend-concurrency-proof
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
# audited_head = git HEAD sha at audit time — freshness stamp. child-result re-checks it: if
# implementation (outside .planning) changed since this sha, the audit is stale (INC-2026-08-06-04).
audited_head: b0024b940e2b7f2b5df269cf256b14fd1edcbdb7
created: 2026-09-04
---

# Phase 04 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Consumer call args → SQL query construction | resource_id, slot_start/slot_end, idempotency_key, and the opaque payload dict cross from the (already Pydantic-validated) engine facade into store.py's SQL query construction. | Structured hold/booking request data |
| Consumer-supplied payload → JSON column | confirm_hold's `payload` argument is untrusted-shaped consumer data that persists into a real database JSON/JSONB column. | Opaque consumer payload |
| testcontainers-generated connection URL → engine construction | `pg_container.get_connection_url()` carries ephemeral, testcontainers-generated credentials for a throwaway container. | Ephemeral DB credentials |
| Consumer-supplied `sqlalchemy.url` at migration-run time | A consumer running `alembic upgrade head` supplies their own connection string via `-x sqlalchemy.url=` or an environment variable; this repo never embeds a real one. | DB connection string |
| N concurrent bookers → one capacity-K slot | The exact trust boundary HOLD-02 exists to defend: independent, uncoordinated callers racing for the same finite resource. | Concurrent hold-placement requests |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-04-01 | Tampering | store.py `place_hold`/`confirm_hold`, locking.py | critical | mitigate | `pg_advisory_xact_lock` as first statement of `place_hold`'s Postgres transaction; SQLite `BEGIN IMMEDIATE` via two-event-listener recipe; empirically proven under real concurrency (`test_concurrency_proof.py::test_concurrent_place_hold_never_exceeds_capacity_k1`/`_k3`). Post-review gap in `confirm_hold` (concurrently-released hold materializing a phantom Booking) closed via commit `66bf076` (rowcount check → `HoldNotFoundError`), covered by regression test `test_concurrent_confirm_and_release_never_leaves_phantom_booking` (commit `6ccfc0f`), verified load-bearing. | closed |
| T-04-02 | Tampering | locking.py, store.py (all query construction) | high | mitigate | Every query uses SQLAlchemy Core `select()`/`insert()`/`update()`/`delete()` or `text()` with named bind parameters exclusively; zero f-string SQL interpolation (grep-confirmed). | closed |
| T-04-03 | Tampering / Information Disclosure | store.py (idempotency table, payload JSON column) | medium | mitigate | `idempotency_key` used only in parameterized WHERE clauses; `payload` stored via parameterized JSON/JSONB column binding; `IntegrityError` translation raises `IdempotencyConflictError` without leaking raw row contents. | closed |
| T-04-SC | Tampering | pip installs (sqlalchemy, asyncpg, aiosqlite, alembic, testcontainers) | high | mitigate | All five packages pre-approved in `.planning/APPROVED-DEPS.md` for Phase 4; pins in `pyproject.toml` match exactly. | closed |
| T-04-04 | Denial of Service | models.py idempotency table | low | accept | Unbounded idempotency-table growth accepted for v1 per CONTEXT.md's deferred section; no reaper built, but `created_at` column exists now so a future retention policy needs no migration. | closed (accepted) |
| T-04-05 | Denial of Service (self-inflicted) | alembic/env.py, library import surface | high | mitigate | Migrations only invoked explicitly via `alembic.command.upgrade`/CLI; `alembic/env.py` has no import-time side effect beyond definitions; zero references to `alembic` under `src/`; no `__init__` triggers a migration. | closed |
| T-04-06 | Information Disclosure | pg_container/pg_engine fixtures (04-02); alembic.ini (04-03) | low/medium | mitigate | Connection URLs are testcontainers-generated/ephemeral, never hardcoded/logged/committed; `alembic.ini`'s `sqlalchemy.url` is a placeholder only, never overwritten with a real credential. | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-04-01 | T-04-04 | Unbounded idempotency-table growth is a real operational cost over time, but a retention/cleanup reaper is explicitly deferred beyond v1 per CONTEXT.md's `<deferred>` section. The `created_at` column exists now so a future retention policy does not require a schema migration. | gsd-security-auditor (automated, ASVS L1) | 2026-09-04 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-04 | 8 | 8 | 0 | gsd-security-auditor |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-04
