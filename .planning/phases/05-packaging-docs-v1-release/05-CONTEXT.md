# Phase 5: Packaging, Docs & v1 Release - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Package the engine as a git-tag-pinnable wheel (migrations included), prove contract conformance against the consumer's shipped suite, ship the async→sync integration adapter, document the contract, and cut the first release tag.

</domain>

<decisions>
## Implementation Decisions

### Release Tag
- **D-01 [version-tag]:** Cut `v0.1.0` — matches the consumer's already-committed pin seam (`tag = "v0.1.0"`, "uncomment once tagged") and the reusable ecosystem's first-tag convention; cutting `v1.0` would orphan the consumer's one-line repin and overstate maturity. _(source: human — confirmed despite the milestone's own `v1.0` label.)_ — **Reversibility:** one-way — a published git tag the consumer repins to.

### Conformance
- **D-02 [conformance]:** Dev-depend on the consumer's already-packaged `AvailabilityContractSuite` (via a pinned consumer git tag, not `main`, in a dev-only dependency group) and subclass it against the engine's real adapter — a re-derived engine-side test can drift silently and defeats the one-suite/many-backends guarantee. _(source: ai-auto)_

### Integration Adapter
- **D-03 [adapter]:** Ship an example-integration adapter that translates the engine's async, reason-code contract into the consumer's sync `AvailabilityPort` (`get_availability`→`query_availability(resource_type, window, party_size)`, reason codes→raised `SlotUnavailable`/`HoldExpired`/`HoldConflict`, the tri-token `cancel(ref)`, uuid4 ids); the engine keeps its native contract. _(source: ai-auto)_ _(provisional — refresh at execution; depends on Phase 2)_ — **Reversibility:** costly — concrete field mapping depends on the Phase 2 frozen contract; refresh once it's frozen.
- **D-04 [async-bridge]:** The engine ships a thin sync facade so the consumer's one-line swap works (the async→sync bridge lives in this repo, not the consumer's composition root). _(source: human — cross-repo coordination decision; determines where the adapter lives.)_ — **Reversibility:** costly — cross-repo contract: the consumer's `port.py` swap depends on where the bridge lives.

### Packaging
- **D-05 [packaging]:** `src`-layout hatchling wheel with an explicit `[tool.hatch.build.targets.wheel] packages` list (auto-discovery fails on `src/`) + the Phase-4 Alembic migrations `force-include`d into the wheel under an importable anchor (`importlib.resources` / `_alembic`-style) — otherwise a git-tag-pinned consumer passes the smoke install but can't bootstrap a schema. Reuse the consumer's template, which already solved this. _(source: ai-auto)_ _(provisional — refresh at execution; depends on Phase 4)_ — **Reversibility:** costly — depends on Phase 4's actual migration layout; refresh once it exists.

### Claude's Discretion
Docs structure and README examples are open provided the contract is documented as the stable product surface.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone decisions
- `.planning/v1.0-DECISION-MAP.md` §Phase 5 — the resolved gray areas above (version-tag, conformance, adapter, async-bridge, packaging)
- `.planning/APPROVED-DEPS.md` — pre-approved packages for this phase (hatchling)

### Upstream (provisional dependencies)
- `.planning/phases/02-capacity-time-correctness/02-CONTEXT.md` — the frozen contract the `adapter` field mapping depends on (refresh `adapter` once frozen).
- `.planning/phases/04-sql-backend-concurrency-proof/04-CONTEXT.md` — the actual Alembic migration layout `packaging` force-includes (refresh `packaging` once it exists).

### Cross-repo (consumer)
- The consumer's `pyproject.toml` pin seam (`tag = "v0.1.0"`), its shipped `AvailabilityContractSuite`, and its `port.py` (`AvailabilityPort`, `to_thread` note) — the async-bridge and conformance decisions coordinate with these.

### Project scope
- `.planning/ROADMAP.md` — Phase 5 scope and success criteria
- `.planning/REQUIREMENTS.md` — release / contract-stability requirements
- `.claude/CLAUDE.md` — reusable-ecosystem packaging convention (uv + hatchling, git-tag pinning)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The consumer already solved wheel-packaging of migrations for a `src`-layout — reuse its template. Surfaced at plan time.

### Established Patterns
- Provide a documented async-via-`asyncio.run()` pattern at the consumer boundary; do not add a sync storage protocol variant (CLAUDE.md) — the thin sync facade (D-04) is the bridge instead.

### Integration Points
- This phase closes the loop with the parallel consumer: the tag, the conformance subclass, and the sync facade are the hand-off surface.

</code_context>

<specifics>
## Specific Ideas

The structured output contract is the product surface — document it as stable and versioned. Confirm the async-bridge location with the consumer owner before planning (decision D-04 sets the default: engine-side facade).

</specifics>

<deferred>
## Deferred Ideas

- None — this is the release phase; deferrals beyond v1 (continuous-duration bookings via `portion`, `FOR UPDATE` tuning) are already tracked in earlier phases and out of the v1 scope.

</deferred>

---

*Phase: 5-Packaging, Docs & v1 Release*
*Context gathered: 2026-09-03*
