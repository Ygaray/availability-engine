# Phase 3: Idempotency & Cancellation - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Make write operations safely retryable (idempotency keys with conflict detection) and model cancellation of confirmed bookings distinctly from hold release, so freed capacity reappears deterministically.

</domain>

<decisions>
## Implementation Decisions

### Idempotency Key Semantics
- **D-01 [key-scope]:** An idempotency key is unique per `(operation_type, key)`, matched exact-string and treated opaquely (the engine never parses or namespaces the key) — mirrors the coarse protocol's distinct atomic methods and the opaque-payload principle. _(source: ai-auto)_
- **D-02 [replay-policy]:** Return the stored original `Hold`/`Booking` on a successful-key replay; a same-key/materially-different-args replay surfaces `idempotency_conflict` (request-fingerprint, Stripe-style); the in-flight race is serialized by the store's single `asyncio.Lock` so the second caller observes the committed record. _(source: ai-auto)_ — **Reversibility:** costly — replay semantics are observable behavior the consumer relies on for retries.
- **D-03 [key-retention]:** Retain idempotency records for the process lifetime in the in-memory store (unbounded dict growth accepted for a dev/test backend, no reaper), consistent with the lazy-on-read / no-runtime-lifecycle rule; the SQL retention/cleanup story is revisited in Phase 4. _(source: ai-auto)_

### Cancellation Model
- **D-04 [cancel-model]:** Cancellation is a distinct operation on **confirmed bookings** (a `cancel_booking` method — not the `release_hold` path, which acts on active holds), modeled as a terminal `cancelled` status excluded from the one shared active-entries predicate — so the freed slot reappears on the next availability read and the not-found/wrong-state rejection stays unambiguous. _(source: ai-auto)_ — **Reversibility:** costly — status model and the shared active-entries predicate are relied on by capacity counting in Phases 2 and 4.

### Claude's Discretion
Request-fingerprint hashing details and the in-memory idempotency record structure are open provided the replay/conflict behavior above holds.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone decisions
- `.planning/v1.0-DECISION-MAP.md` §Phase 3 — the resolved gray areas above (key-scope, replay-policy, key-retention, cancel-model)
- `.planning/APPROVED-DEPS.md` — no new packages expected this phase; escalate any at execution.

### Upstream contract
- `.planning/phases/02-capacity-time-correctness/02-CONTEXT.md` — the closed reason-code enum pre-seeds `idempotency_conflict` (raised here); the shared active-entries predicate cancellation must integrate with.
- `.planning/phases/01-end-to-end-walking-skeleton-in-memory/01-CONTEXT.md` — protocol signatures: idempotency key arrives as a defaulted kwarg / new method, never a changed existing signature.

### Project scope
- `.planning/ROADMAP.md` — Phase 3 scope and success criteria
- `.planning/REQUIREMENTS.md` — atomicity / safe-retry requirements

### External reference
- Stripe idempotency spec — worth a targeted read before freezing the replay/conflict semantics (request-fingerprint model).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The single `asyncio.Lock` in the in-memory store (from Phase 1) serializes the in-flight idempotency race. Surfaced at plan time.

### Established Patterns
- Lazy-on-read expiry (no background sweeper) — idempotency retention follows the same no-runtime-lifecycle rule.

### Integration Points
- The `cancelled` terminal status feeds the shared active-entries predicate used by availability/capacity reads.

</code_context>

<specifics>
## Specific Ideas

No specific requirements beyond the decisions above — open to standard Stripe-style idempotency approaches.

</specifics>

<deferred>
## Deferred Ideas

- SQL-backed idempotency uniqueness (unique constraint) and retention/cleanup → Phase 4 (`schema`, `key-retention` SQL story).

</deferred>

---

*Phase: 3-Idempotency & Cancellation*
*Context gathered: 2026-09-03*
