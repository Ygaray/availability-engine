---
phase: 05
slug: packaging-docs-v1-release
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
# audited_head = git HEAD sha at audit time — freshness stamp. child-result re-checks it: if
# implementation (outside .planning) changed since this sha, the audit is stale (INC-2026-08-06-04).
audited_head: b27353a98c8f33d82807282e5c4962ceae267348
created: 2026-09-04
EOF_note: "Original audit ran against a60ccb6 (post code-review-fix pass); UF-1 was fixed at b27353a after the audit and is folded into this record — see Audit Trail."
---

# Phase 05 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| this repo's dev environment → sibling consumer repo | the `conformance` dependency group pulls SocialNetwork-Chatbot's full transitive dev tree (anthropic, structlog, sqlalchemy, aiosqlite, alembic, pydantic-settings, tenacity, pyyaml) as dev-only installs, pinned to a real git tag on a private repo, never shipped to a library consumer | Cross-repo dev dependency resolution |
| example adapter → consumer's opaque bearer tokens | hold_id/booking_id/confirmation_ref/slot_id function as unauthenticated bearer capability tokens in the consumer's own port design (no separate auth layer) — a predictable id or an unhandled malformed token would let any caller cancel/confirm another conversation's hold or crash the adapter | Caller-supplied slot_id / hold_id / booking_id strings |
| tagged commit → every future consumer pin | once `v0.1.0` is pushed, it is treated as immutable — every consumer that resolves it gets exactly this commit forever | Immutable release artifact |
| wheel build → installed consumer environment | force-included Alembic migrations must be importable and runnable post-install, not just present in `src/` at dev time | Packaged migration files |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-05-01 | Tampering / Info Disclosure | `pyproject.toml` force-include table, wheel build | medium | mitigate | `tests/packaging/test_wheel_contains_migrations.py` asserts `py.typed` + migrations present AND zero `examples/`/`chatbot_adapter` entries in the built wheel namelist. | closed |
| T-05-02 | Information Disclosure | `tests/packaging/test_bootstrap_installed_wheel.py` | low | accept | Smoke-install test only ever uses an ephemeral `sqlite+aiosqlite:///./smoke_migrate.db` inside a tmp dir, never a real credential. | closed (accepted) |
| T-05-03 | Information Disclosure | `src/availability_engine/sync.py` | medium | mitigate | No logging/print of call arguments or exceptions; `_call()` re-raises `future.result()` unchanged with no message interpolation. | closed |
| T-05-04 | Denial of Service | `src/availability_engine/sync.py` (background-thread bridge) | medium | mitigate | Post-review-fix: `close()` raises `RuntimeError` if the background thread doesn't join within 5s (WR-04), calls `self._loop.close()` after a successful join (IN-02), and `_call()` fails fast with `RuntimeError` (not a hang) if the loop is closed/not running, with a bounded 30s default timeout on `future.result()` (WR-01). Daemon thread; `tests/test_sync_facade.py` green including post-close regression tests. | closed |
| T-05-05 | Spoofing | `examples/chatbot_adapter.py` id surfacing (hold_id/booking_id/confirmation_ref) | medium | mitigate | uuid4 minted exactly once per hold in both storage backends (`storage/memory.py`, `storage/sql/store.py`) and reused as the booking id in both; the adapter never mints its own id — verified by full read and live-value cross-check. | closed |
| T-05-06 | Information Disclosure | `examples/chatbot_adapter.py` exception translation | medium | mitigate | `errors.py` constructors interpolate only identifiers (resource_id/hold_id/booking_id/operation_type/key), never payload/details content; the adapter's own catch blocks construct `SlotUnavailable()`/`HoldConflict()`/`HoldExpired()` with zero arguments. | closed |
| T-05-SC | Tampering / Supply-chain | `pyproject.toml [dependency-groups] conformance` (dev-only git-source dependency) | medium | mitigate | Isolated `conformance` group never pulled by a plain `uv sync`; `[tool.uv.sources]` pins `tag = "v1.0"` (never `main`) against `github.com/Ygaray/SocialNetwork-Chatbot`, live-verified PRIVATE, with `uv.lock`'s resolved commit matching `git ls-remote --tags origin` exactly. Repo creation/visibility was an explicit operator decision (05-03 Task 1 checkpoint), not a silent default. | closed |
| T-05-07 | Documentation-accuracy | `README.md` | low | mitigate | Post-review-fix: Sync example inlines the same literal `datetime(...)` values as the async example (no undefined names); "7 async methods" (was miscounted "6"); concurrency-proof test path corrected; wheel-vs-checkout `alembic upgrade head` caveat clarified as dev-checkout-only. | closed |
| T-05-08 | Tampering | `v0.1.0` git tag (cut before verification, or from the wrong commit) | high | mitigate | No `v0.1.0` tag exists yet (`git tag -l` / `git ls-remote --tags origin` both empty at audit time) — the gate is holding as designed. `05-05-PLAN.md` Task 1 (`checkpoint:human-verify`, blocking) still gates Task 2's tag-cut; not yet executed. | closed (gate holding, not yet exercised) |
| UF-1 | Denial of Service / Input Validation | `examples/chatbot_adapter.py::place_hold` (malformed `slot_id` parse) | medium | mitigate | Flagged by the security audit as an unregistered gap (not in the original threat register): `json.loads(slot_id)` + tuple unpack + `datetime.fromisoformat()` had no error handling, so a malformed/tampered caller-supplied `slot_id` raised a raw `JSONDecodeError`/`ValueError`/`TypeError` instead of the typed `SlotUnavailable` the `AvailabilityPort` contract otherwise guarantees. Fixed post-audit at commit `b27353a`: the parse block now raises `SlotUnavailable()` on any of those three exception types. Regression test `test_place_hold_raises_slot_unavailable_for_malformed_slot_id` added. | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-05-01 | T-05-02 | Smoke-install test uses only an ephemeral local SQLite file inside a tmp dir; no real credential ever appears in test fixtures or logs. No further action needed. | gsd-security-auditor (automated, ASVS L1) | 2026-09-04 |

---

## Informational Notes (non-blocking, below block_on threshold)

- **UF-2 (process/freshness):** the pre-fix `05-VERIFICATION.md` (dated before the code-review-fix pass) cited stale test counts. Superseded — see the refreshed `05-VERIFICATION.md` addendum recorded alongside this audit, which reflects the current `137 passed` / `13 passed` (conformance) counts at HEAD `b27353a`.
- **UF-3 (design note, informational only):** `chatbot_adapter.py`'s `threading.Lock` around `_hold_keys`/`_confirmed_keys` correctly guards both mutation sites but leaves a narrow TOCTOU window between the `_confirmed_keys` check and a concurrently-running `confirm_hold` populating it. This cannot cause an actual double-hold (the storage layer's atomic fingerprint+capacity logic is the real enforcement point, proven in earlier phases) — worst case is a misclassified exception type on a tightly-raced retry. No action required; noted for future hardening if this reference adapter is copied into a high-concurrency production composition root.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-04 | 9 (+1 unregistered: UF-1) | 10 | 0 | gsd-security-auditor + orchestrator fix (UF-1, commit `b27353a`) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter
- [x] Unregistered finding (UF-1) triaged and closed before tag-cut checkpoint

**Approval:** verified 2026-09-04 (SECURED, 0 open threats at or above `block_on: high`)
