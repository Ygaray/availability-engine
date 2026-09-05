# Phase 3: Idempotency & Cancellation - Research

**Researched:** 2026-09-04
**Domain:** Retry-safe write operations (idempotency keys) and terminal-state cancellation, in a single-process, `asyncio.Lock`-guarded in-memory storage backend
**Confidence:** MEDIUM-HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 [key-scope]:** An idempotency key is unique per `(operation_type, key)`, matched exact-string and treated opaquely (the engine never parses or namespaces the key) — mirrors the coarse protocol's distinct atomic methods and the opaque-payload principle.

**D-02 [replay-policy]:** Return the stored original `Hold`/`Booking` on a successful-key replay; a same-key/materially-different-args replay surfaces `idempotency_conflict` (request-fingerprint, Stripe-style); the in-flight race is serialized by the store's single `asyncio.Lock` so the second caller observes the committed record. — **Reversibility:** costly — replay semantics are observable behavior the consumer relies on for retries.

**D-03 [key-retention]:** Retain idempotency records for the process lifetime in the in-memory store (unbounded dict growth accepted for a dev/test backend, no reaper), consistent with the lazy-on-read / no-runtime-lifecycle rule; the SQL retention/cleanup story is revisited in Phase 4.

**D-04 [cancel-model]:** Cancellation is a distinct operation on **confirmed bookings** (a `cancel_booking` method — not the `release_hold` path, which acts on active holds), modeled as a terminal `cancelled` status excluded from the one shared active-entries predicate — so the freed slot reappears on the next availability read and the not-found/wrong-state rejection stays unambiguous. — **Reversibility:** costly — status model and the shared active-entries predicate are relied on by capacity counting in Phases 2 and 4.

### Claude's Discretion

Request-fingerprint hashing details and the in-memory idempotency record structure are open provided the replay/conflict behavior above holds.

### Deferred Ideas (OUT OF SCOPE)

- SQL-backed idempotency uniqueness (unique constraint) and retention/cleanup → Phase 4 (`schema`, `key-retention` SQL story).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HOLD-06 | Consumer can cancel a confirmed Booking, freeing its capacity | New `cancel_booking` facade + storage-protocol method; terminal `BookingStatus.CANCELLED` excluded from `get_active_entries` (the one shared active-entries primitive) — see Architecture Patterns, Code Examples |
| HOLD-07 | `place_hold`/`confirm` accept an optional idempotency key; a retry with the same key returns the original result instead of acting twice | Idempotency record keyed by `(operation_type, key)` with request-fingerprint conflict detection, checked and stored inside the existing `asyncio.Lock` critical section — see Architecture Patterns, Code Examples, Stripe/brandur research below |

</phase_requirements>

## Summary

This phase adds no new external dependency — everything needed (`dataclasses`, `enum.StrEnum`, `json`, `hashlib`) is stdlib, and `.planning/APPROVED-DEPS.md` [VERIFIED: .planning/APPROVED-DEPS.md] has no Phase 3 entries, confirming none are expected. The work is entirely inside the existing `StorageBackend` Protocol and `InMemoryStore`, both of which already reserved the shape this phase needs: `place_hold`/`confirm_hold` already declare `idempotency_key: str | None = None` on the Protocol [VERIFIED: src/availability_engine/storage/protocol.py:29,39] (Phase 1's forward-compatible-signatures decision paid off exactly as designed), and `ReasonCode` already includes `IDEMPOTENCY_CONFLICT` [VERIFIED: src/availability_engine/contracts.py:159-163] as a closed, pre-seeded value. The two things that are genuinely new — and not yet reserved anywhere in the codebase — are (1) an idempotency record store keyed by `(operation_type, key)` with request-fingerprint comparison, and (2) a `status` field on `Booking` distinguishing `confirmed` from a terminal `cancelled` state, since `Booking` today has no such field [VERIFIED: src/availability_engine/contracts.py:192-198] and `get_active_entries` currently treats every stored `Booking` as permanently active [VERIFIED: src/availability_engine/storage/memory.py:65-72, quoting inline comment "Bookings have no expiry — cancellation is Phase 3's HOLD-06, out of scope here."].

Targeted research into Stripe's idempotency model (its blog post and Brandur Leach's widely-cited Postgres-oriented writeup, cross-checked against each other — MEDIUM confidence, [CITED: stripe.com/blog/idempotency], [CITED: brandur.org/idempotency-keys]) confirms the shape D-01/D-02 already lock in: a record keyed by the idempotency key stores a **request fingerprint** (the semantically relevant request parameters, not timestamps or key order) alongside the eventual result; a replay with a matching fingerprint returns the stored result, a replay with a mismatched fingerprint is rejected as a conflict, and concurrent racing requests are serialized by whatever the backend's native atomicity primitive is (a DB unique constraint + lock-timestamp for Stripe/Brandur's Postgres case; this project's single `asyncio.Lock` for the in-memory case). No new insight from that research changes the locked decisions — it confirms them and supplies concrete implementation shape for the parts CONTEXT.md left to discretion (fingerprinting details, record structure).

**Primary recommendation:** Implement idempotency entirely inside `InMemoryStore` (never at the `AvailabilityEngine` facade) as a `dict[tuple[str, str], IdempotencyRecord]` checked-and-written inside the same `async with self._lock:` block that already guards `place_hold`/`confirm_hold` — no new lock, no new await inside the critical section. Add a `status: BookingStatus` field (default `CONFIRMED`) to `Booking`, add `cancel_booking` to both the Protocol and `InMemoryStore`, and update `get_active_entries` to skip `CANCELLED` bookings — mirroring the exact pattern already used to skip expired holds.

## Architectural Responsibility Map

> Adapted tier vocabulary: this is a single-process Python **library**, not a multi-tier web application — the generic Browser/SSR/API/CDN/DB tiers from the standard template don't apply. The project's own architecture (per `01-PATTERNS.md` and the System Architecture Diagram below) has exactly three tiers: **Facade** (`AvailabilityEngine`, thin passthrough + boundary validation), **Storage Backend** (`StorageBackend` Protocol + `InMemoryStore`, owns all atomicity and the check-and-write patterns), and **Contract Types** (`contracts.py`, the frozen public shapes).

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Idempotency key conflict/replay detection | Storage Backend | — | Must execute inside the same locked critical section as the mutation it guards (D-02's race-serialization requirement); the facade never takes a lock itself [VERIFIED: src/availability_engine/engine.py:1-6, quoting docstring "The facade never takes a lock itself; atomicity lives entirely behind the StorageBackend Protocol"] |
| Request fingerprint computation | Storage Backend | — | Computed from the same args the storage method already receives; no new data crosses the facade boundary — `idempotency_key` is already a reserved Protocol kwarg [VERIFIED: src/availability_engine/storage/protocol.py:29,39] |
| Idempotency key passthrough on `place_hold`/`confirm_hold` | Facade | Storage Backend | Facade adds the param as a new defaulted kwarg (per D-04 in Phase 1's protocol-signatures decision) and forwards it unchanged; storage does the actual work |
| Cancellation of a confirmed Booking | Storage Backend | Facade | `cancel_booking` mutates the one authoritative `_bookings` dict under the lock; facade exposes a thin public method mirroring `release_hold`'s existing shape [VERIFIED: src/availability_engine/engine.py:119-121] |
| Terminal `cancelled` status exclusion from capacity counting | Storage Backend | — | `get_active_entries` is "the ONE shared, expiry-filtering active-entries primitive" [VERIFIED: src/availability_engine/storage/memory.py:40-44, quoting inline comment] every read/write path already calls; cancellation exclusion extends this same function, not a new one |
| Contract shape (`Booking.status`, new exceptions) | Contract Types | — | `BookingStatus` enum and `IdempotencyConflictError`/`BookingNotFoundError` are new public surface — must be added to `contracts.py`/`errors.py` and re-exported from `__init__.py` [VERIFIED: src/availability_engine/__init__.py:1-37] |

## Standard Stack

### Core

No new runtime dependencies. This phase is implementable entirely with stdlib already available in the pinned Python 3.12+ target:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `dataclasses` (stdlib) | n/a | `IdempotencyRecord` internal value object (frozen, slotted) | Matches the existing internal-value-object convention (`core/intervals.py`'s `Interval`) [VERIFIED: src/availability_engine/core/intervals.py:13-19] — never crosses the public boundary, so Pydantic is unnecessary overhead per the project's established two-tier type split |
| `enum.StrEnum` (stdlib) | n/a | `BookingStatus` enum (`CONFIRMED`/`CANCELLED`) | Matches the existing `SlotStatus`/`ReasonCode` pattern, both already `StrEnum` [VERIFIED: src/availability_engine/contracts.py:142-163] |
| `json` + `hashlib` (stdlib) | n/a | Canonical request-fingerprint hashing (`json.dumps(..., sort_keys=True, default=str)` → `hashlib.sha256(...).hexdigest()`) | Matches the Stripe/Brandur research pattern of hashing "the semantic fields of a request body (not timestamps or field order)" [CITED: stripe.com/blog/idempotency] without pulling in a third-party canonicalization library for a problem stdlib already solves |

### Supporting

Already-installed dev/test tooling from prior phases — no new pins needed:

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.1.1 [VERIFIED: pyproject.toml] | Test runner | All new tests |
| `pytest-asyncio` | 1.4.0 [VERIFIED: pyproject.toml] | Async test functions | `AvailabilityEngine`/`InMemoryStore` are async-only |
| `hypothesis` | 6.167.1 [VERIFIED: pyproject.toml] | Property-based tests | Good fit for "N concurrent retries with the same key always converge to exactly one stored result" invariants, if the planner wants a property test alongside the deterministic ones |
| `time-machine` | 3.5.0 [VERIFIED: pyproject.toml] | Time mocking | Not obviously needed this phase (no new TTL/expiry logic) unless idempotency retention windowing is tested — D-03 explicitly defers retention/TTL to Phase 4, so likely unused here |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Storing a `sha256` fingerprint string | Storing the raw comparison tuple directly (no hash) | Simpler for the in-memory backend (direct `==` comparison, no hashing needed at all since nothing serializes). Rejected in favor of hashing now because Phase 4 defers "SQL-backed idempotency uniqueness" — a `fingerprint_hash TEXT` column is the natural SQL shape, and computing the hash now keeps the in-memory and SQL backends structurally aligned for the shared contract-suite tests (STORE-04). This is explicitly a discretionary choice per CONTEXT.md, not a locked decision — the planner may choose either. |
| `Booking.status` as a `BookingStatus` enum field | A `cancelled_at: UtcDatetime \| None` sentinel field (mirrors the "half-open interval" / lazy-expiry idiom already used for `Hold.expires_at`) | Either satisfies D-04's "terminal cancelled status" language. An explicit enum was chosen for this research's worked examples because D-04's wording ("modeled as a terminal `cancelled` status") reads more literally as a status field, and it composes with a `StrEnum` the same way `SlotStatus` already does. This is flagged as an assumption (see Assumptions Log) since CONTEXT.md left the exact field shape to discretion. |

**Installation:** None required.

**Version verification:** No new packages to verify. Existing pins reconfirmed by reading `pyproject.toml` directly this session (`pydantic==2.13.5`, `tzdata==2026.3`, `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `ruff==0.16.6`, `mypy==2.3.1`, `time-machine==3.5.0`, `hypothesis==6.167.1`) [VERIFIED: pyproject.toml].

## Package Legitimacy Audit

**No external packages are installed or added in this phase.** `.planning/APPROVED-DEPS.md` [VERIFIED: .planning/APPROVED-DEPS.md] lists approved packages only for Phases 1, 2, 4, and 5 — none for Phase 3, matching `03-CONTEXT.md`'s explicit note: "no new packages expected this phase; escalate any at execution." If the planner's task breakdown surfaces an unexpected need for a new package (it should not, based on this research), that package must be escalated to a human per the standard flow — do not silently add anything to `pyproject.toml`.

**Packages removed due to `[SLOP]` verdict:** none
**Packages flagged as suspicious `[SUS]`:** none

## Architecture Patterns

### System Architecture Diagram

**Idempotent `place_hold` (and, structurally identically, `confirm_hold`):**

```
Consumer
  │  place_hold(resource_id, slot_start, slot_end, ttl_seconds, idempotency_key=None)
  ▼
AvailabilityEngine.place_hold()          [existing: resource lookup, hours validation]
  │  forwards idempotency_key unchanged (new defaulted kwarg — D-04/Phase1 protocol rule)
  ▼
InMemoryStore.place_hold(..., idempotency_key)
  │
  ▼  async with self._lock:                                    (existing lock, no new await)
  ├─ idempotency_key is not None?
  │     │
  │     ├─ (op="place_hold", key) found in _idempotency?
  │     │     ├─ fingerprint matches new args ──► return stored Hold          (D-02: replay)
  │     │     └─ fingerprint differs           ──► raise IdempotencyConflictError (D-02: conflict)
  │     │
  │     └─ not found ──► fall through to the existing capacity-check path ↓
  │
  ├─ get_active_entries() capacity check          [existing, AVAIL-03 primitive, unchanged]
  │     ├─ exhausted ──► raise CapacityExhaustedError  (key NOT stored — see Assumptions Log A2)
  │     └─ ok ──► create Hold, store in _holds          [existing]
  │
  └─ idempotency_key is not None ──► store IdempotencyRecord(fingerprint, result=Hold)
                                       under (op="place_hold", key)
  ▼
return Hold
```

**`cancel_booking` (new, HOLD-06):**

```
Consumer
  │  cancel_booking(booking_id)
  ▼
AvailabilityEngine.cancel_booking()      [new: thin passthrough, mirrors release_hold's shape]
  ▼
InMemoryStore.cancel_booking(booking_id)
  │
  ▼  async with self._lock:
  ├─ booking = _bookings.get(booking_id)
  ├─ missing, or booking.status == BookingStatus.CANCELLED
  │     └─► raise BookingNotFoundError(booking_id)      (D-04: "not-found/wrong-state ...unambiguous")
  └─ else ──► _bookings[booking_id] = booking.model_copy(update={"status": BookingStatus.CANCELLED})
  ▼
(next) get_active_entries() skips CANCELLED bookings   [modified: one new `continue` branch]
  ▼
get_availability() / place_hold() capacity counts reflect the freed slot immediately (HOLD-06 success criterion #3)
```

### Recommended Project Structure

No new files this phase — every change extends an existing module:

```
src/availability_engine/
├── contracts.py       # + BookingStatus enum; + Booking.status field (default CONFIRMED)
├── errors.py           # + IdempotencyConflictError; + BookingNotFoundError
├── engine.py           # + idempotency_key kwarg on place_hold/confirm_hold; + cancel_booking method
├── storage/
│   ├── protocol.py     # + cancel_booking(booking_id, ...) -> None
│   └── memory.py       # + _idempotency dict + check-and-store logic; + cancel_booking; get_active_entries skips CANCELLED
└── __init__.py         # + export new public names

tests/
├── conftest.py                       # (unchanged, or + a second sample_resource fixture if needed)
├── test_engine.py                    # + idempotent place_hold/confirm tests; + cancel_booking tests
├── test_errors.py                    # + IdempotencyConflictError / BookingNotFoundError to the exhaustiveness list
└── storage/contract_suite.py         # + idempotency + cancel_booking cases, so Phase 4's SQL backend is
                                       #   exercised against the same behavior automatically (STORE-04)
```

### Pattern 1: Idempotency record, checked and written inside the existing lock

**What:** A `dict[tuple[str, str], IdempotencyRecord]` on `InMemoryStore`, keyed by `(operation_type, key)` per D-01. Checked at the start of the locked critical section; written at the end, only on success.
**When to use:** Any storage-protocol method that accepts `idempotency_key`.
**Example:**
```python
# New in storage/memory.py — pattern derived from D-01/D-02 and the existing
# lock-guarded check-and-write shape already used for capacity (Pitfall 1 mirror).
import hashlib
import json
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    fingerprint: str
    result: Hold | Booking  # whichever type the operation produces


def _fingerprint(*parts: object) -> str:
    canonical = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# on InMemoryStore:
_idempotency: dict[tuple[str, str], IdempotencyRecord] = field(default_factory=dict)

# inside place_hold, before the capacity check, still under `async with self._lock:`:
if idempotency_key is not None:
    fp = _fingerprint(resource_id, slot.start, slot.end, ttl_seconds)
    existing = self._idempotency.get(("place_hold", idempotency_key))
    if existing is not None:
        if existing.fingerprint == fp:
            assert isinstance(existing.result, Hold)
            return existing.result
        raise IdempotencyConflictError("place_hold", idempotency_key)
# ... existing capacity check + Hold creation unchanged ...
if idempotency_key is not None:
    self._idempotency[("place_hold", idempotency_key)] = IdempotencyRecord(fp, hold)
return hold
```
*(Source: derived from this project's existing lock-guarded check-and-write shape [VERIFIED: src/availability_engine/storage/memory.py:84-112] combined with Stripe/Brandur's fingerprint-then-store pattern [CITED: stripe.com/blog/idempotency, brandur.org/idempotency-keys]. This is new code, not a verbatim frozen contract — flagged `[ASSUMED]` as a discretionary implementation choice per CONTEXT.md.)*

### Pattern 2: Terminal `cancelled` status excluded from the shared active-entries primitive

**What:** Extend `get_active_entries`'s existing booking loop with one `continue` for cancelled bookings — the same idiom already used for expired holds.
**When to use:** Anywhere a Booking's "is it still occupying capacity" question is asked.
**Example:**
```python
# Existing code (verbatim) [VERIFIED: src/availability_engine/storage/memory.py:65-72]:
# for booking in self._bookings.values():
#     # Bookings have no expiry — cancellation is Phase 3's HOLD-06,
#     # out of scope here.
#     if booking.resource_id != resource_id:
#         continue
#     booking_interval = Interval(start=booking.slot_start, end=booking.slot_end)
#     if overlaps(booking_interval, window):
#         entries.append(booking)

# Phase 3 modification — add ONE branch, mirroring the hold-expiry `continue` above it:
for booking in self._bookings.values():
    if booking.resource_id != resource_id:
        continue
    if booking.status == BookingStatus.CANCELLED:
        continue
    booking_interval = Interval(start=booking.slot_start, end=booking.slot_end)
    if overlaps(booking_interval, window):
        entries.append(booking)
```
*(Source: existing file content, quoted verbatim per in-repo value provenance rule; the added branch is `[ASSUMED]` new code following the file's own established idiom.)*

### Anti-Patterns to Avoid

- **Computing/storing the idempotency record outside the lock, or after an `await`:** reopens exactly the TOCTOU window `place_hold`'s capacity check was already fixed to close (Pitfall 1 in this codebase's own history) — two concurrent same-key retries could both pass the "not found" check before either writes.
- **Making `cancel_booking` silently idempotent like `release_hold`:** `release_hold` deliberately no-ops on an unknown/already-released `hold_id` (`self._holds.pop(hold_id, None)`) [VERIFIED: src/availability_engine/storage/memory.py:137-139]. D-04 explicitly wants cancellation's not-found/wrong-state rejection to "stay unambiguous" — copying `release_hold`'s pattern here would be a deliberate misread of the locked decision.
- **Widening `ReasonCode`:** it is closed by design (D-03 in Phase 2) [VERIFIED: src/availability_engine/contracts.py:153-157, quoting "Closed, one-way enum (D-03) — a consumer can exhaustiveness-match on this."]. New exceptions this phase (`IdempotencyConflictError`, `BookingNotFoundError`) must reuse `ReasonCode.IDEMPOTENCY_CONFLICT` and `ReasonCode.NOT_FOUND` respectively — never add a new enum member.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Canonical JSON for fingerprint hashing | A hand-rolled recursive dict-sorter | `json.dumps(obj, sort_keys=True, default=str)` | stdlib already does deterministic key-ordering; a hand-rolled sorter is a classic source of subtle fingerprint-mismatch bugs (e.g. missing nested-dict recursion) |
| Distributed/cross-process locking for the idempotency race | Any lock library, Redis `SETNX`, etc. | The existing single `asyncio.Lock` already guarding all `InMemoryStore` mutations | D-03/this backend is explicitly single-process, dev/test-scoped; a distributed lock solves a problem this backend doesn't have (Phase 4's SQL backend gets its own dialect-aware atomicity story per `.claude/CLAUDE.md`, separately) |
| A background reaper for stale idempotency records | Any scheduled task / thread / asyncio task | Nothing — D-03 explicitly accepts unbounded dict growth for this backend | Matches the project's established "no background sweeper, lazy-on-read only" rule already applied to hold expiry; a reaper here would be inconsistent with that precedent and out of scope until Phase 4 |

**Key insight:** Every piece this phase needs (fingerprint hashing, race serialization, terminal-status filtering) already has a working analog somewhere in this exact codebase from Phases 1–2. The implementation task is almost entirely "extend the existing pattern one more time," not "introduce a new mechanism."

## Common Pitfalls

### Pitfall 1: Idempotency check happens outside the lock's critical section
**What goes wrong:** Two coroutines both pass the "no existing record for this key" check before either writes one, so both execute the underlying operation — exactly the TOCTOU bug this codebase's own history already had to fix once for capacity checking.
**Why it happens:** It's tempting to check-then-call-then-store as three separate statements/awaits instead of one atomic block.
**How to avoid:** Check, execute, and store the record all inside the same `async with self._lock:` block with no intervening `await`, exactly like `place_hold`'s existing capacity check [VERIFIED: src/availability_engine/storage/memory.py:84-112].
**Warning signs:** Any `await` between "look up the idempotency key" and "write the result under it."

### Pitfall 2: Storing the idempotency key on failure paths too
**What goes wrong:** If a `CapacityExhaustedError` (or any rejection) is cached under the key, a legitimate retry after capacity frees up gets permanently stuck replaying the old failure instead of succeeding.
**Why it happens:** Treating "the operation was attempted under this key" and "the operation succeeded under this key" as the same event.
**How to avoid:** Only write the `IdempotencyRecord` on the success path, after the `Hold`/`Booking` is created — this is the interpretation this research recommends for HOLD-07 (see Assumptions Log A2); flagged as an assumption because CONTEXT.md doesn't explicitly resolve it.
**Warning signs:** A test asserting "retry after the underlying state changed should now succeed" fails because the store returns a cached error.

### Pitfall 3: Fingerprint computed without `sort_keys=True`
**What goes wrong:** Two calls with logically identical `payload` dicts (same keys, different insertion order) produce different JSON strings, hash differently, and a legitimate replay is misclassified as a conflict.
**Why it happens:** `json.dumps` without `sort_keys=True` preserves insertion order by default.
**How to avoid:** Always pass `sort_keys=True` (and `default=str` to handle `datetime` values in `place_hold`'s fingerprint inputs).
**Warning signs:** A retry test with a payload dict constructed in a different key order than the original intermittently fails.

### Pitfall 4: Forgetting the `get_active_entries` update, so cancellation doesn't actually free capacity
**What goes wrong:** `cancel_booking` flips `status` to `CANCELLED`, but `get_active_entries` still counts the record — the phase's third success criterion ("the freed slot reappears on the next availability read") silently fails even though the booking object itself looks cancelled.
**Why it happens:** Cancellation touches two independent pieces of code (the mutation, and the read-side filter); it's easy to ship one without the other since neither's test alone would catch the gap.
**How to avoid:** Any test proving HOLD-06 must go through `get_availability` (or `place_hold` re-succeeding on the same slot) after `cancel_booking`, not just assert `booking.status == CANCELLED` in isolation — mirrors the existing `test_release_hold_frees_capacity` pattern [VERIFIED: tests/test_engine.py:177-197].
**Warning signs:** A unit test on `cancel_booking` passes in isolation while an end-to-end availability test after cancellation still shows the slot as booked.

### Pitfall 5: Key-scope collision across operations
**What goes wrong:** Using a single `dict[str, IdempotencyRecord]` keyed only by the raw key string (not `(operation_type, key)`) means the same key string reused for `place_hold` and `confirm_hold` collides — violating D-01 and potentially returning a `Hold` where a `Booking` was expected (or vice versa) to a caller.
**Why it happens:** It looks simpler to have one flat dict.
**How to avoid:** Always key by the `(operation_type, key)` tuple, per D-01, never a bare string.
**Warning signs:** A test using the same idempotency key string for both a `place_hold` and an unrelated `confirm_hold` call unexpectedly returns the wrong type or a spurious conflict.

### Pitfall 6: Forgetting to export new public names
**What goes wrong:** `IdempotencyConflictError`, `BookingNotFoundError`, and/or `BookingStatus` are added to `errors.py`/`contracts.py` but never added to `__init__.py`'s `__all__` — a consumer catching `AvailabilityEngineError` still works (base-class catch), but anyone trying `from availability_engine import IdempotencyConflictError` for a narrower `except` gets an `ImportError`.
**Why it happens:** `__init__.py`'s export list [VERIFIED: src/availability_engine/__init__.py:1-37] is a separate file from where the new symbols are defined — easy to miss in a diff review.
**How to avoid:** Treat `__init__.py` as part of the phase's file-touch list, not an afterthought; add a test asserting the new names are importable from the top-level package (mirrors `test_errors.py`'s existing exhaustiveness-list pattern [VERIFIED: tests/test_errors.py:14-20]).
**Warning signs:** None at the unit-test level if no test imports from the top-level package — this is a silent gap unless explicitly tested.

## Code Examples

### Existing reason-code closed enum (verbatim — must be reused, not widened)
```python
# Source: src/availability_engine/contracts.py:153-164 (read this session)
class ReasonCode(StrEnum):
    """Closed, one-way enum (D-03) — a consumer can exhaustiveness-match on
    this. `IDEMPOTENCY_CONFLICT` is reserved: only Phase 3 raises it, but it
    is pre-included here so widening the enum later isn't required.
    """

    CAPACITY_EXHAUSTED = "capacity_exhausted"
    OUTSIDE_HOURS = "outside_hours"
    HOLD_EXPIRED = "hold_expired"
    NOT_FOUND = "not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
```

### Existing exception shape to mirror for the two new exceptions
```python
# Source: src/availability_engine/errors.py:57-64 (read this session) — mirror
# this exact shape for BookingNotFoundError (reason_code=ReasonCode.NOT_FOUND)
# and IdempotencyConflictError (reason_code=ReasonCode.IDEMPOTENCY_CONFLICT).
# Never accept or store a payload/args argument on either — mirrors T-01-01
# (no exception message may ever carry consumer payload contents).
class HoldNotFoundError(AvailabilityEngineError):
    """Raised when a hold_id does not refer to a currently active hold."""

    reason_code = ReasonCode.NOT_FOUND

    def __init__(self, hold_id: str) -> None:
        self.hold_id = hold_id
        super().__init__(f"hold {hold_id!r} not found")
```

### Existing reserved Protocol kwargs (verbatim — already frozen from Phase 1, no change needed)
```python
# Source: src/availability_engine/storage/protocol.py:22-43 (read this session)
async def place_hold(
    self,
    resource_id: str,
    slot: Interval,
    capacity: int,
    ttl_seconds: int,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,  # reserved for Phase 3 — never rename
) -> Hold: ...

async def confirm_hold(
    self,
    hold_id: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,  # reserved for Phase 3
) -> Booking: ...
```
Note the `place_hold` Protocol signature already reserves `payload` too, even though the current `AvailabilityEngine.place_hold` facade doesn't accept one [VERIFIED: src/availability_engine/engine.py:85-112] — only `idempotency_key` is this phase's concern; do not surface `payload` on `place_hold`'s facade unless a separate requirement calls for it (none does).

## State of the Art

Not applicable in the traditional sense (no external library/API version drift to track — this is an internal, stdlib-only extension of an already-established in-house pattern). The one relevant "current practice" note: Stripe's own public idempotency documentation has stayed conceptually stable for years (opaque client-supplied key + header, ≥24h retention, fingerprint-based conflict detection) — nothing about the target-domain best practice has shifted recently enough to matter for this phase's design [CITED: stripe.com/blog/idempotency, docs.stripe.com/api/idempotent_requests].

**Deprecated/outdated:** None applicable.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Booking` gets a new `status: BookingStatus` enum field (`CONFIRMED`/`CANCELLED`, default `CONFIRMED`) as the concrete shape of D-04's "terminal cancelled status" | Architecture Patterns (Pattern 2), Alternatives Considered | Low-medium: an alternative shape (`cancelled_at: UtcDatetime \| None`) would satisfy D-04 equally well and is a smaller diff (one nullable field vs. a new enum type + field); if the planner picks the alternative, the `get_active_entries` filter condition changes from `status == CANCELLED` to `cancelled_at is not None` but the overall architecture is unaffected |
| A2 | A failed `place_hold`/`confirm_hold` attempt (e.g. `CapacityExhaustedError`, `HoldExpiredError`) does **not** consume or store the idempotency key — only a successful result is cached, so a retry after a failure is free to re-attempt | Common Pitfalls (Pitfall 2), Architecture Patterns diagram | Medium: if the intended behavior is instead "cache and deterministically replay failures too" (closer to some readings of Stripe's actual behavior for certain error classes), a retry after a transient failure would behave differently than tested here; HOLD-07's requirement text ("returns the original result") reads as being about successful results specifically, which is why this was assumed rather than the alternative |
| A3 | `cancel_booking` raises `BookingNotFoundError` (reason_code=`NOT_FOUND`) both when `booking_id` doesn't exist at all and when it refers to an already-cancelled booking — no silent idempotent no-op (unlike `release_hold`) | Architecture Patterns (Anti-Patterns), Common Pitfalls | Medium: this directly implements D-04's "not-found/wrong-state rejection stays unambiguous" phrase, but the exact reused `ReasonCode` for the "wrong state" (already-cancelled) case specifically isn't spelled out in CONTEXT.md — reusing `NOT_FOUND` mirrors the existing `ResourceNotFoundError`/`HoldNotFoundError` precedent of sharing one code for conceptually distinct "not found" targets |
| A4 | `cancel_booking` does **not** accept an `idempotency_key` parameter in this phase — only `place_hold`/`confirm_hold` do, per HOLD-07's literal requirement text | Architecture Patterns (Recommended Project Structure) | Low: HOLD-06's requirement text has no idempotency-key language at all; adding one later as a defaulted kwarg would be non-breaking per the established forward-compatible-signature convention if this assumption turns out wrong |
| A5 | Fingerprint hashing uses `json.dumps(parts, sort_keys=True, default=str)` → `hashlib.sha256(...).hexdigest()`, stored as a string, rather than storing the raw comparison tuple directly | Standard Stack (Alternatives Considered), Code Examples (Pattern 1) | Low: purely an implementation-shape choice explicitly left to discretion by CONTEXT.md; either approach satisfies D-02's observable replay/conflict behavior identically from the consumer's point of view |
| A6 | The `place_hold` fingerprint covers `(resource_id, slot_start, slot_end, ttl_seconds)` — meaning a retry with the same key must also supply the same `ttl_seconds`, or it is treated as a conflict; the `confirm_hold` fingerprint covers `(hold_id, payload)` | Code Examples (Pattern 1) | Medium: if a caller's retry logic doesn't re-send an identical `ttl_seconds` (e.g. it recomputes a fresh TTL each attempt), this would misfire as `idempotency_conflict` on an otherwise-legitimate retry — worth confirming with the planner/discuss-phase whether `ttl_seconds` should be excluded from the fingerprint |

**If this table is empty:** N/A — see entries above. All locked decisions (D-01 through D-04) are implemented as specified; the assumptions above are exclusively in the discretionary space CONTEXT.md explicitly left open, plus one full-file-open shape (`Booking.status`) that D-04 describes conceptually but does not pin to an exact field.

## Open Questions (RESOLVED)

1. **Should `ttl_seconds` be part of `place_hold`'s idempotency fingerprint?**
   - What we know: D-02 says a "materially-different-args replay" surfaces a conflict; `ttl_seconds` is technically a call argument.
   - What's unclear: whether a caller's retry is expected to resend the exact same `ttl_seconds` value, or whether TTL is considered "not semantically material" (since the resulting `Hold.expires_at` is server-computed from `now() + ttl_seconds` at call time anyway, and a replay returns the *original* `Hold` regardless).
   - Recommendation: Exclude `ttl_seconds` from the fingerprint unless the planner/discuss-phase decides otherwise — it's the one field most likely to legitimately differ between a caller's initial attempt and its retry (e.g. a client library that recomputes a "remaining timeout budget" per attempt), and excluding it doesn't weaken conflict detection on the fields that actually identify *which slot* is being held (`resource_id`, `slot_start`, `slot_end`).
   - **RESOLVED:** 03-02-PLAN.md's Task 1 follows this recommendation literally — the `place_hold` fingerprint excludes `ttl_seconds`, covering only `(resource_id, slot_start, slot_end)`.

2. **Exact `Booking` cancellation field shape — `status` enum vs. `cancelled_at` sentinel.**
   - What we know: D-04 says "modeled as a terminal `cancelled` status"; both a `BookingStatus` enum and a nullable `cancelled_at` timestamp satisfy this literally.
   - What's unclear: which one CONTEXT.md's author actually had in mind — the wording favors "status" but the codebase's other precedent (`Hold.expires_at`) favors the sentinel-timestamp idiom.
   - Recommendation: This research's worked examples use the `BookingStatus` enum (see Assumptions Log A1) for concreteness, but flag this explicitly for the planner to confirm or override before committing to `contracts.py` changes — it is the one true "new public contract shape" decision this phase makes that CONTEXT.md doesn't pin down exactly.
   - **RESOLVED:** 03-01-PLAN.md's Task 1 adopts the `BookingStatus` enum (`CONFIRMED`/`CANCELLED`, default `CONFIRMED`) on `Booking`, matching Assumption A1's recommendation.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 [VERIFIED: pyproject.toml] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`; `python_files` includes `contract_suite.py`) [VERIFIED: pyproject.toml] |
| Quick run command | `uv run pytest tests/test_engine.py tests/test_errors.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HOLD-07 | `place_hold` with same key + same args returns original `Hold`, no second capacity consumption | integration (facade-level, mirrors `test_release_hold_frees_capacity`) | `uv run pytest tests/test_engine.py::test_place_hold_idempotent_replay -x` | ❌ Wave 0 |
| HOLD-07 | `place_hold` with same key + different args raises `IdempotencyConflictError` w/ `reason_code == ReasonCode.IDEMPOTENCY_CONFLICT` | integration | `uv run pytest tests/test_engine.py::test_place_hold_idempotency_conflict -x` | ❌ Wave 0 |
| HOLD-07 | `confirm_hold` same-key replay returns original `Booking` | integration | `uv run pytest tests/test_engine.py::test_confirm_hold_idempotent_replay -x` | ❌ Wave 0 |
| HOLD-07 | Storage-level idempotency behavior holds for any current/future backend | contract-suite (parametrized, STORE-02/04) | `uv run pytest tests/storage/contract_suite.py -x` | ❌ Wave 0 — add cases to existing file |
| HOLD-06 | `cancel_booking` on a confirmed booking frees capacity — freed slot reappears in `get_availability`/accepts a new `place_hold` | integration (mirrors `test_release_hold_frees_capacity`) | `uv run pytest tests/test_engine.py::test_cancel_booking_frees_capacity -x` | ❌ Wave 0 |
| HOLD-06 | `cancel_booking` on an unknown or already-cancelled booking raises `BookingNotFoundError` (`reason_code == ReasonCode.NOT_FOUND`) | integration | `uv run pytest tests/test_engine.py::test_cancel_booking_not_found_or_already_cancelled -x` | ❌ Wave 0 |
| HOLD-08 (regression) | New exceptions (`IdempotencyConflictError`, `BookingNotFoundError`) both carry a non-None `ReasonCode` | unit (extends existing exhaustiveness test) | `uv run pytest tests/test_errors.py -x` | ✅ file exists — extend `_CONCRETE_EXCEPTION_CLASSES` list [VERIFIED: tests/test_errors.py:14-20] |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_engine.py tests/test_errors.py -x`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_engine.py` — add idempotency-replay, idempotency-conflict, and cancel-booking test functions (file exists, new test functions needed)
- [ ] `tests/test_errors.py` — extend `_CONCRETE_EXCEPTION_CLASSES` with `IdempotencyConflictError` and `BookingNotFoundError`
- [ ] `tests/storage/contract_suite.py` — add idempotency and cancel_booking cases to the shared parametrized suite, so Phase 4's SQL backend addition is exercised against identical behavior (STORE-04's whole purpose)
- [ ] No new fixture files or framework install needed — `time_machine`/`pytest-asyncio`/`hypothesis` already present and already imported by `contract_suite.py` [VERIFIED: tests/storage/contract_suite.py:1-16]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Out of scope — library has no auth surface |
| V3 Session Management | no | Out of scope |
| V4 Access Control | no | Out of scope — engine trusts its caller (the consumer application) for authorization, per the project's one-way-dependency boundary |
| V5 Input Validation | yes | Idempotency key is treated as an **opaque string** (D-01) — never parsed, never used to construct a path/query/format string. No new validation library needed; existing Pydantic boundary validation pattern (`contracts.py`) is the standard control if the planner decides to bound key length |
| V6 Cryptography | yes (narrow) | `hashlib.sha256` for fingerprint hashing is a non-cryptographic-secrecy use (collision-resistance for fingerprint comparison, not confidentiality) — stdlib `hashlib` is the correct, non-hand-rolled choice; do not invent a custom hash/checksum |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unbounded idempotency-dict growth from a caller minting unique keys per request (memory-exhaustion DoS) | Denial of Service | **Explicitly accepted risk for this phase** — D-03 locks in "unbounded dict growth accepted for a dev/test backend, no reaper," deferred to Phase 4's SQL retention story. Document this as a known, deliberate limitation in `PKG-02`'s eventual concurrency-guarantees docs (Phase 5) rather than attempting a fix here — adding a reaper now would violate the established "no background sweeper / lazy-on-read only" rule and contradict D-03. |
| Payload/fingerprint leaking into an exception message (information disclosure) | Information Disclosure | Mirror the existing rule already enforced throughout `errors.py`: no exception constructor accepts or stores a `payload`/args argument [VERIFIED: src/availability_engine/errors.py:1-11, quoting docstring "Every constructor accepts only non-sensitive identifiers ... and never accepts or stores a payload argument"]. `IdempotencyConflictError` must take only `(operation_type, key)` — never the conflicting args or payload — in its constructor/message. |
| Idempotency-key reuse across operations misrouting a `Hold` where a `Booking` is expected (or vice versa) | Tampering / logic confusion | D-01's `(operation_type, key)` scoping, enforced structurally by the dict key tuple (Pitfall 5 above) — not a runtime "attack" so much as a correctness/logic-confusion risk with security-adjacent consequences (returning the wrong typed object to a caller expecting type-safe branching) |

## Sources

### Primary (HIGH confidence — read directly this session)
- `src/availability_engine/contracts.py` — `ReasonCode`, `Booking`, `Hold`, `SlotStatus` shapes
- `src/availability_engine/errors.py` — exception hierarchy and constructor conventions
- `src/availability_engine/engine.py` — facade method shapes
- `src/availability_engine/storage/protocol.py` — reserved `idempotency_key` Protocol kwargs
- `src/availability_engine/storage/memory.py` — lock-guarded check-and-write pattern, `get_active_entries` shared primitive
- `src/availability_engine/core/intervals.py` — internal value-object convention
- `pyproject.toml` — pinned dependency versions, pytest config
- `tests/test_engine.py`, `tests/test_errors.py`, `tests/storage/contract_suite.py`, `tests/conftest.py` — existing test conventions
- `.planning/phases/01-.../01-CONTEXT.md`, `.planning/phases/02-.../02-CONTEXT.md`, `.planning/v1.0-DECISION-MAP.md` §Phases 1-3, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/APPROVED-DEPS.md`, `.planning/config.json` — upstream decision/requirement context

### Secondary (MEDIUM confidence — WebSearch/WebFetch, cross-checked across two independent sources)
- [Designing robust and predictable APIs with idempotency](https://stripe.com/blog/idempotency) — Stripe's own conceptual model
- [Idempotent requests — Stripe API docs](https://docs.stripe.com/api/idempotent_requests?lang=node) — key format, header usage, retention window (≥24h)
- [Implementing Stripe-like Idempotency Keys in Postgres — brandur.org](https://brandur.org/idempotency-keys) — concrete storage schema, fingerprinting, lock-timeout-based concurrency

### Tertiary (LOW confidence — WebSearch only, general pattern confirmation, not separately cited as authoritative claims)
- General "idempotency key + unique constraint + race condition" pattern articles surfaced during the Python/asyncio search (used only to confirm the check-and-execute-atomically pattern is universally recommended, not for any specific claim in this document)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, entirely stdlib, versions confirmed by reading `pyproject.toml` directly
- Architecture: MEDIUM — extends verified existing patterns faithfully, but the exact `Booking` cancellation field shape and fingerprint field selection are discretionary/assumed (see Assumptions Log, Open Questions)
- Pitfalls: MEDIUM — grounded in this codebase's own documented history (Pitfall 1's TOCTOU precedent) plus cross-checked external idempotency research

**Research date:** 2026-09-04
**Valid until:** 2026-10-04 (30 days — stable, stdlib-only domain; no fast-moving external dependency to track)
