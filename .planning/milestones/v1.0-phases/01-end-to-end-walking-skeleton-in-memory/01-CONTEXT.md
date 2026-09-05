# Phase 1: End-to-End Walking Skeleton (In-Memory) - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a working end-to-end availability + atomic-hold flow against an in-memory backend, freezing the public contract types and storage/engine signatures the parallel consumer stubs against — no SQL, no DST math yet.

</domain>

<decisions>
## Implementation Decisions

### Contract & Types
- **D-01 [contract-types]:** Pydantic v2 at the public output/input boundary (gives the parallel consumer an exportable JSON schema to stub against) + `@dataclass(frozen=True, slots=True)` for engine-internal value objects (`Slot`, interval endpoints, internal `Hold` state). _(source: human — resolves the STACK.md vs ARCHITECTURE.md conflict deliberately; the stub pins to whatever ships.)_ — **Reversibility:** one-way — the consumer's stub pins to the published contract shape; changing the boundary type system after the pin breaks the consumer.
- **D-02 [payload]:** The opaque consumer payload is a JSON-serializable `dict`, attached at confirm and round-tripped verbatim on the `Booking` — composes cleanly with the Pydantic-serialized output contract. _(source: ai-auto)_

### Resource & Hours Shape
- **D-03 [hours-shape]:** A Resource's per-weekday operating hours are a list-of-half-open-intervals per weekday (already permits overnight/split shifts), chosen now to physically accommodate overnight/split hours even though correct midnight-crossing generation is deferred to Phase 2 — avoids a breaking `Resource` input change after the consumer pins. _(source: ai-auto)_ — **Reversibility:** one-way — a published `Resource` input shape the consumer pins to.

### Protocol & Signatures
- **D-04 [protocol-signatures]:** Freeze forward-compatible `StorageBackend` Protocol and `AvailabilityEngine` facade signatures now; reserve payload/ttl params, and let Phase 2/3 additions (reason codes, idempotency key, `expire_holds`) arrive as defaulted kwargs or new methods — never as changed existing signatures, so the SQL backend and the consumer stub don't break. _(source: ai-auto)_ — **Reversibility:** costly — later phases and the consumer stub bind to these signatures.

### Tooling & Pins
- **D-05 [tooling]:** Enforce strict `ruff` + `mypy --strict` on `src/` from commit 1 — catches contract drift and naive-datetime leaks before they accumulate across four phases; retrofitting strict typing late is a large cleanup. _(source: ai-auto)_
- **D-06 [versions]:** Re-verify exact PyPI version pins against PyPI at implementation time (Pydantic 2.13.x, pytest-asyncio 0.24.x+, ruff 0.9.x+, mypy 1.13.x+) rather than pinning blindly from the research snapshot; defer the SQL/testcontainers stack to Phase 4. _(source: ai-auto)_

### Claude's Discretion
Internal module layout, exact `Slot`/`Interval` field names, and in-memory store internals are open provided they honor the frozen public contract above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone decisions
- `.planning/v1.0-DECISION-MAP.md` §Phase 1 — the resolved gray areas above (contract-types, hours-shape, protocol-signatures, payload, tooling, versions)
- `.planning/APPROVED-DEPS.md` — pre-approved packages for this phase (pydantic, ruff, mypy, pytest, pytest-asyncio)

### Project scope
- `.planning/ROADMAP.md` — Phase 1 scope and success criteria
- `.planning/REQUIREMENTS.md` — v1 requirements the contract must satisfy
- `.claude/CLAUDE.md` — locked stack, constraints (UTC-internal, one-way dep, async storage protocol, contract stability)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- No source code yet — this is the first implementation phase. Surfaced at plan time.

### Established Patterns
- Reusable-ecosystem convention: `uv` + `hatchling`, `src/` layout, git-tag pinning by consumers (per CLAUDE.md).

### Integration Points
- The parallel reusable booking chatbot backend codes against this phase's stubbed contract — the public types and signatures are the integration surface.

</code_context>

<specifics>
## Specific Ideas

The contract is the product surface — it must be stable and documented. Freeze conservatively so Phases 2–5 extend without breaking the pin.

</specifics>

<deferred>
## Deferred Ideas

- Correct midnight-crossing slot generation → Phase 2 (`midnight-hours`).
- DST-transition representation → Phase 2 (`dst-contract`).
- Idempotency key + reason codes as defaulted params/new methods → Phase 3.
- SQL backend + version pins for the SQL/testcontainers stack → Phase 4.

</deferred>

---

*Phase: 1-End-to-End Walking Skeleton (In-Memory)*
*Context gathered: 2026-09-03*
