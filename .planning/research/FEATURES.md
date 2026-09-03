# Feature Research

**Domain:** Domain-agnostic availability/scheduling engine (library, not end-user app)
**Researched:** 2026-09-02
**Confidence:** MEDIUM

## Framing

This is a **library**, not a product. "Users" here means **consumer developers** (the chatbot
backend, and future consumers) who import the engine and call its API — not end-customers booking
a slot. Table stakes = features a consumer developer needs or they can't safely build a booking
flow on top of this engine at all. Differentiators = what makes this engine pleasant/safe to build
on versus a naive roll-your-own. Anti-features = end-user-app concerns that would break the
domain-agnostic contract or blow up scope, correctly deferred to the consumer or a later milestone.

## Feature Landscape

### Table Stakes (Consumer Developers Expect These)

Missing these = the engine cannot be safely used to build a real booking flow.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Resource model with capacity ≥1, per-day operating hours, buffer/reset time | The core domain object every query and hold operates against | LOW | Already in PROJECT.md scope; capacity=1 is the degenerate case of capacity>1, so build for N from day one |
| Fixed-duration slot grid generation (hours + slot length + buffer → discrete slots) | Deterministic availability requires a canonical partition of time; ad-hoc interval math invites off-by-one and DST bugs | MEDIUM | Depends on Resource model + TZ handling. Grid must be regenerable, not stored — stored slots go stale when hours change |
| Single-resource ranged availability query (available/booked windows over a date range) | The #1 call a consumer makes: "show me open slots for resource X this week" | MEDIUM | Depends on slot grid + existing holds/bookings read. Must be capacity-aware (a slot is "available" until capacity is exhausted, not just until 1 booking exists) |
| Capacity-aware remaining-count per slot | Consumers building UI (e.g. "3 of 5 seats left") need a count, not just a boolean | LOW | Free once availability is capacity-aware internally — just don't collapse the count to a boolean before it leaves the contract |
| Atomic hold placement (reject if capacity exhausted, single indivisible operation) | This is the core value prop stated in PROJECT.md — "no two bookers can ever double-book." Without atomicity the engine is just a read-only calendar | HIGH | Depends on storage protocol supporting a real atomic primitive (row lock, conditional UPDATE, or unique constraint) — this is the single hardest correctness property in the whole library |
| Hold → confirm → booking lifecycle | Every reservation-style system needs a "propose then commit" flow to survive payment/confirmation steps that happen outside the engine | MEDIUM | Depends on atomic hold. Confirm should be atomic too (hold must still be valid/unexpired at confirm time) |
| Explicit hold release | A consumer that abandons a flow (user closes chat) needs to give back capacity without waiting for TTL | LOW | Depends on hold model |
| TTL-based hold expiry, lazy-on-read | Prevents abandoned holds from permanently locking capacity, without the library owning a background process (explicit non-goal in PROJECT.md) | MEDIUM | Depends on hold model + storage read path checking expiry on every relevant query, not just at write time |
| Idempotency key on hold/confirm operations | Chatbots and HTTP consumers retry on timeout; without idempotency a retried "place hold" call can double-consume capacity or a retried "confirm" can double-book | MEDIUM-HIGH | Depends on storage layer (unique constraint on the idempotency key + operation type). Table-stakes for any network-facing consumer, easy to underestimate |
| Opaque consumer payload attachment on booking | The engine names zero domain concepts, so all domain data (party size, contact info, escape-room team name, salon customer) must ride along as an opaque blob the engine stores and returns unopened | LOW | Depends on booking model. Must be schema-less (JSON blob / bytes) from the engine's point of view |
| Operating-hours + blackout respecting availability | Availability computed without honoring "resource closed on this day/time" is simply wrong | LOW-MEDIUM | Depends on Resource model's per-day hours. Ad-hoc blackout dates are cheap even if full RRULE recurrence is deferred (see Anti-Features) |
| TZ-aware, UTC-internal computation with per-resource IANA zone | Scheduling engines that get DST wrong silently double-book or vanish an hour once or twice a year — this is a correctness property, not a nice-to-have | HIGH | Cross-cutting: touches slot grid generation, operating-hours evaluation, and hold TTL math. Get this wrong and every other feature inherits the bug |
| Pluggable async storage protocol + in-memory reference implementation | A library that hard-codes one backend can't be adopted by consumers with different infra, and can't be unit-tested without spinning up a real DB | MEDIUM | Foundational — nearly everything else (atomicity, TTL expiry, idempotency) is a contract the storage backend must satisfy, defined by this protocol |
| At least one production-grade storage implementation with real atomicity (SQL: SQLite + Postgres) | The in-memory backend proves the contract; a SQL backend proves it survives concurrent processes/requests, which is the actual deployment shape | HIGH | Depends on storage protocol. Row-level locking / `SELECT ... FOR UPDATE` or a conditional `UPDATE ... WHERE` is the concrete mechanism |
| Stable, documented structured output contract (available/booked shapes) | This is explicitly the product surface per PROJECT.md — a parallel consumer is coding against it before the engine is done | HIGH (as a design problem, not implementation) | Everything else emits into this contract; getting the shape wrong late means breaking a parallel consumer. See "Output Contract" section below |
| Cancellation of a confirmed booking (return capacity) | A booking system that can hold and confirm but never release a confirmed slot back to inventory isn't usable past a single event | LOW-MEDIUM | Depends on booking model; symmetric to hold release but must free confirmed (not held) capacity |

### Differentiators (Competitive Advantage for a Library)

Not required for a minimally usable engine, but what makes it worth adopting over rolling your own,
or over a heavier general-purpose tool.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Multi-resource availability query ("first available across N resources") | Real consumers (chatbot) often don't care which chair/room, just the earliest opening — saves the consumer from querying N resources and merging client-side | MEDIUM | Depends on single-resource availability; is a fan-out + merge over the same primitive, not new correctness surface |
| Next-available convenience query (vs. only ranged windows) | Common conversational-bot pattern ("what's your next opening?") that's needlessly awkward to express as a date-range scan every time | LOW | Depends on ranged availability; thin sugar over it |
| Rescheduling as a first-class atomic operation (not cancel+rebook) | Cancel-then-rebook has a race window where another booker can steal the slot between the two calls; a single atomic reschedule closes that gap | MEDIUM-HIGH | Depends on atomic hold + confirmed-booking model; reuses the same atomic-transition primitive as hold placement |
| Free/busy window output mode (merged intervals) alongside discrete slot-list mode | Some consumers want a calendar-style rendering (busy blocks), others want a slot picker (discrete buttons) — supporting both view shapes off one internal model avoids consumers reimplementing interval-merging themselves | MEDIUM | Depends on the output contract; both are derived views over the same available/booked truth, so this is a formatting feature, not a modeling one |
| Rich rejection reasons on failed holds (capacity exhausted vs. outside hours vs. conflicting blackout vs. expired) | A consumer building a chatbot needs to say something more useful than "no" — "that slot is full" vs "we're closed then" changes the bot's reply | LOW-MEDIUM | Depends on availability + hold logic already discriminating these cases internally for its own correctness |
| Deterministic, replayable slot-grid math exposed as a pure function (no I/O) | Lets consumers unit-test their own booking UI logic against the exact same grid the engine would produce, without a DB — valuable for a contract-first parallel consumer | LOW-MEDIUM | Depends on slot grid generation already being decoupled from storage reads (which it should be for testability anyway) |
| Interval math designed to extend to arbitrary-duration bookings without rework | Explicit PROJECT.md decision — v1 ships fixed-grid only, but the differentiator is *not painting yourself into a corner* | MEDIUM (as a design constraint on v1, not a v1 feature) | This is a non-feature (nothing shipped in v1) but a design discipline: represent slots/holds as `[start, end)` intervals internally even while the public API only emits grid-aligned slots |

### Anti-Features (Deliberately Out of Scope for This Library)

These are common in full booking *products* but wrong for a domain-agnostic *engine* — either
because they bloat scope, bake in domain assumptions, or belong one layer up in the consumer.

| Feature | Why It Seems Appealing | Why Problematic Here | Alternative |
|---------|------------------------|-----------------------|-------------|
| Recurrence rules (RRULE), holidays, one-off closures/overrides | Every real calendar needs "closed on holidays" and "repeats weekly" eventually | Recurrence expansion is its own well-known iceberg (RRULE edge cases, exception dates, DST interactions) — pulling it in now couples v1 scope to a much bigger problem than "compute today's slots." Already an explicit PROJECT.md deferral | Ship ad-hoc, per-day operating-hours + a simple blackout-date list in v1 (cheap, covers "closed on holidays" without a recurrence engine); layer a proper RRULE-based calendar module on top in a later milestone, expanding into the same per-day-hours primitive the engine already consumes |
| Arbitrary-duration / continuous-interval bookings | More "correct" model of real-world time than a fixed grid | Continuous-interval overlap detection is strictly harder (interval trees / exclusion constraints) than grid-slot lookups, and the first consumer doesn't need it | Fixed-duration grid in v1; keep internal representation as `[start, end)` intervals (see differentiator above) so this can be added later without a rewrite |
| Pricing / payments | Booking and paying feel like one flow to an end user | Pricing is a domain concept (the engine names zero domain concepts) and payment integration pulls in PCI/webhook/refund complexity entirely orthogonal to availability correctness | Consumer attaches price/payment-status as part of its opaque payload on the booking, and orchestrates payment itself (e.g., confirm the hold only after payment succeeds) |
| Notifications (email/SMS/push reminders) | "You have a booking in 1 hour" is expected by end users | Notification delivery is infrastructure (queues, providers, templates) that has nothing to do with computing availability, and would force the library to own scheduling of its own background jobs — directly conflicting with the "no background sweeper" decision | Consumer reads booking start times from the contract and drives its own reminder/notification system |
| User/auth/identity | Every booking is "by" someone | Identity and authz are consumer concerns; baking in a user model would force a domain vocabulary (which the engine explicitly must not have) and duplicate whatever auth system the consumer already has | Consumer identity rides inside the opaque payload attached at booking time; the engine never inspects "who" |
| UI / rendering | Consumers want to show a calendar/slot-picker | A domain-agnostic engine has no idea what a "chair" or "room" looks like in UI, and coupling to any UI framework limits reuse across wildly different consumers (chatbot vs. web app) | Engine emits the structured contract (slots, remaining capacity, free/busy windows); every consumer renders it in whatever UI fits its channel |
| Calendar-provider sync (Google/Outlook two-way sync) | "Show my bookings in my Google Calendar" is a common ask | Sync is a whole integration surface (OAuth, webhooks, conflict resolution between two sources of truth) unrelated to computing availability correctly, and it's explicitly framed in PROJECT.md as "this engine owns the resource/capacity/hold model; calendars are an optional future adapter" | Treat as a future export/sync adapter that reads the engine's structured contract and pushes to external calendars — never a dependency of the core engine |
| Waitlists | "Notify me if this slot opens up" is a nice booking-product feature | Waitlists require notification delivery (already excluded) plus a fairness/ordering policy that is inherently domain-specific (first-come vs. priority tiers) — not a core availability-correctness concern | Consumer can poll availability queries or maintain its own waitlist keyed by resource/slot, and re-query the engine when notified externally |
| Background sweeper / active hold-expiry process | Feels more "real-time" than lazy expiry — holds visibly disappear the instant they expire | A library should not own a runtime lifecycle (own threads/processes/cron); it can't assume how or where the consumer deploys it, and lazy-on-read is deterministic and trivially testable, whereas a sweeper introduces a second write path that must stay consistent with the read path | Auto-release expired holds lazily whenever a query or hold-attempt touches them — already the PROJECT.md decision |
| Additional storage backends beyond in-memory + SQL (Redis, NoSQL, etc.) in v1 | Redis is the de-facto pattern in high-contention public reservation systems (Ticketmaster-style) research above | Adding a second backend before the storage *protocol* itself is proven and stable multiplies surface area for no v1 consumer benefit — the async storage protocol already keeps this door open | Ship the storage protocol + in-memory (tests) + one SQL impl (SQLite/Postgres) in v1; a Redis-backed implementation is a natural, low-risk future addition against the same protocol once it exists |

## Feature Dependencies

```
Resource model (capacity, hours, buffer, TZ)
    └──requires──> nothing (foundational)

Slot grid generation
    └──requires──> Resource model
    └──requires──> TZ-aware time handling

Single-resource ranged availability query
    └──requires──> Slot grid generation
    └──requires──> Storage read of existing holds/bookings

Capacity-aware remaining-count per slot
    └──requires──> Single-resource ranged availability query

Multi-resource / next-available query
    └──requires──> Single-resource ranged availability query   [DIFFERENTIATOR]

Atomic hold placement
    └──requires──> Storage protocol with an atomic write primitive
    └──requires──> Slot grid generation (to validate the requested slot exists)

Hold → confirm → booking
    └──requires──> Atomic hold placement

Explicit hold release
    └──requires──> Atomic hold placement

TTL hold expiry (lazy-on-read)
    └──requires──> Atomic hold placement
    └──requires──> Storage read path checking expiry

Idempotency key on hold/confirm
    └──requires──> Storage protocol (unique-constraint support)
    └──enhances──> Atomic hold placement, Hold → confirm → booking

Opaque payload attachment
    └──requires──> Hold → confirm → booking

Cancellation of confirmed booking
    └──requires──> Hold → confirm → booking

Rescheduling (atomic)
    └──requires──> Atomic hold placement
    └──requires──> Cancellation of confirmed booking            [DIFFERENTIATOR]

Rich rejection reasons
    └──enhances──> Atomic hold placement, availability query    [DIFFERENTIATOR]

Free/busy window output mode
    └──requires──> Single-resource ranged availability query    [DIFFERENTIATOR]

Storage protocol + in-memory impl
    └──requires──> nothing (foundational; must exist before atomic hold placement can be implemented)

SQL storage impl (SQLite/Postgres)
    └──requires──> Storage protocol

Structured output contract
    └──requires──> Availability query + Hold/booking lifecycle shapes to stabilize against
    └──conflicts if unstable with──> Parallel consumer development (contract-first requirement)

Recurrence (RRULE)                                               [ANTI-FEATURE, deferred]
    └──would require──> Resource model, Slot grid generation (as an upstream input, not a rework)

Arbitrary-duration bookings                                      [ANTI-FEATURE, deferred]
    └──would require──> Internal `[start, end)` interval representation kept from v1 [DIFFERENTIATOR]
```

### Dependency Notes

- **Everything correctness-critical funnels through the storage protocol.** Atomic hold placement,
  TTL expiry, and idempotency keys are all *contracts the storage backend must satisfy* — the
  protocol must be designed before any of them can be implemented correctly, which is why
  PROJECT.md and this research both treat "pluggable async storage protocol + in-memory impl" as
  the true foundation, not the Resource model.
- **TZ-aware time handling is cross-cutting, not a separate feature.** It must be baked into slot
  grid generation and operating-hours evaluation from the start; retrofitting timezone correctness
  onto a naive-datetime engine later is a rewrite, not a patch.
- **The structured output contract is downstream of every other feature's shape**, but must be
  designed *first* in practice because a parallel consumer (the chatbot) codes against a stub of it
  immediately. This is a sequencing tension worth flagging for the roadmap: design/document the
  contract early (even before every feature behind it is fully implemented), then backfill features
  to satisfy it.
- **Rescheduling conflicts with naive cancel+rebook.** Doing reschedule as two separate calls
  (cancel, then book) reopens the exact race the atomic hold exists to prevent — a competing booker
  can grab the slot in between. If rescheduling ships, it must reuse the atomic hold-transition
  primitive directly, not compose two public calls.
- **Recurrence and arbitrary-duration bookings are correctly deferred, but the v1 design should not
  foreclose them.** Keeping the internal time representation as intervals (even though v1's public
  API only emits grid-aligned slots) is what makes both future anti-features cheap to add later
  instead of requiring a rewrite — this is the one place where a deferred anti-feature still
  constrains today's implementation choices.

## The Output Contract (Design Notes, Not a Feature List)

Since PROJECT.md calls the structured output contract "the product surface," a few concrete shape
recommendations, informed by how Cal.com/Calendly split this problem:

- **Two output *modes* over one underlying truth**, not two separate models:
  - **Slot-list mode** — discrete, grid-aligned slots, each carrying `{start, end, resource_id,
    capacity_total, capacity_remaining, status}` where `status` is `available | held | booked |
    closed`. Best for UI slot-pickers (what a booking chatbot needs).
  - **Free/busy window mode** — merged contiguous intervals of `available` vs. `booked` time per
    resource. Best for calendar-style rendering. Derivable from slot-list mode by merging adjacent
    same-status slots — do not maintain it as a separate source of truth.
- **Capacity must be a count, not a boolean**, all the way through — collapsing `capacity_remaining`
  to an `available: bool` anywhere in the pipeline loses information a consumer may need (e.g. "3
  left" changes chatbot phrasing) and is irreversible once collapsed.
- **Rejections need a machine-readable reason code**, not just a failure — `capacity_exhausted`,
  `outside_operating_hours`, `blackout`, `hold_expired`, `not_found`, `idempotency_conflict` — so
  the consumer chatbot can phrase a specific reply instead of a generic "sorry, that didn't work."
- **The opaque payload must round-trip untouched.** The engine should treat it as an opaque
  `bytes`/`dict` blob it stores and returns verbatim on booking read — any temptation to add
  structure to it (e.g. "party_size" as a named field) is domain leakage and violates the
  zero-domain-vocabulary constraint.

## MVP Definition

### Launch With (v1)

Everything in PROJECT.md's Active requirements, ordered by dependency:

- [ ] Storage protocol (async) + in-memory implementation — nothing else is buildable without this
- [ ] Resource model (capacity, per-day hours, buffer, IANA TZ)
- [ ] TZ-aware slot grid generation from Resource + slot length + buffer
- [ ] Single-resource ranged availability query, capacity-aware, respecting hours
- [ ] Atomic hold placement with capacity check, backed by the storage protocol
- [ ] Hold → confirm → booking with opaque payload attachment
- [ ] Explicit hold release + lazy TTL expiry
- [ ] Idempotency keys on hold/confirm operations
- [ ] Cancellation of a confirmed booking
- [ ] SQL storage implementation (SQLite + Postgres) with real atomicity
- [ ] Documented, stable structured output contract (slot-list mode at minimum)

### Add After Validation (v1.x)

Trigger: the first consumer (chatbot) hits a real need for these in production use.

- [ ] Multi-resource / next-available query — once a consumer needs "any open chair," not just "chair 3"
- [ ] Free/busy window output mode — once a consumer wants calendar-style rendering, not just a slot list
- [ ] Rescheduling as a first-class atomic operation — once cancel+rebook race conditions actually surface
- [ ] Rich, discriminated rejection reason codes — once a consumer needs to phrase specific failure messages

### Future Consideration (v2+)

Explicitly deferred per PROJECT.md; revisit only when a consumer's real need forces it.

- [ ] Recurrence rules (RRULE) + holiday/blackout calendars — big scope, layer on top of per-day hours later
- [ ] Arbitrary-duration / continuous-interval bookings — requires interval-tree-style overlap detection
- [ ] Redis (or other) storage backend — add once the protocol is proven stable against 2 backends
- [ ] Calendar-provider sync adapter (Google/Outlook) — external integration, not core engine scope

## Feature Prioritization Matrix

| Feature | Consumer Value | Implementation Cost | Priority |
|---------|-----------------|---------------------|----------|
| Storage protocol + in-memory impl | HIGH | MEDIUM | P1 |
| Resource model | HIGH | LOW | P1 |
| TZ-aware slot grid generation | HIGH | HIGH | P1 |
| Ranged availability query (capacity-aware) | HIGH | MEDIUM | P1 |
| Atomic hold placement | HIGH | HIGH | P1 |
| Hold → confirm → booking + opaque payload | HIGH | MEDIUM | P1 |
| Explicit release + lazy TTL expiry | HIGH | MEDIUM | P1 |
| Idempotency keys | HIGH | MEDIUM-HIGH | P1 |
| SQL storage impl (SQLite/Postgres) | HIGH | HIGH | P1 |
| Cancellation | MEDIUM | LOW-MEDIUM | P1 |
| Structured output contract documentation | HIGH | HIGH (design effort) | P1 |
| Multi-resource / next-available | MEDIUM | MEDIUM | P2 |
| Free/busy window output mode | MEDIUM | MEDIUM | P2 |
| Rescheduling (atomic) | MEDIUM | MEDIUM-HIGH | P2 |
| Rich rejection reason codes | MEDIUM | LOW-MEDIUM | P2 |
| Recurrence / RRULE / blackout calendars | LOW (for v1 consumer) | HIGH | P3 |
| Arbitrary-duration bookings | LOW (for v1 consumer) | HIGH | P3 |
| Redis storage backend | LOW | MEDIUM | P3 |
| Calendar sync adapter | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch (matches PROJECT.md's Active requirements)
- P2: Should have, add when the first real consumer need appears
- P3: Nice to have, explicitly out of scope per PROJECT.md until a later milestone

## Comparable Systems Analyzed

| Concern | Cal.com / Calendly (SaaS scheduling APIs) | Ticketmaster-style high-contention reservation systems | This Engine's Approach |
|---------|--------------------------------------------|----------------------------------------------------------|--------------------------|
| Availability output | Derived slot-list / free-busy view computed from schedule + bookings, not stored | N/A (seat maps are pre-enumerated inventory, not generated slots) | Same principle: availability is always computed from Resource + hold/booking state, never stored as its own truth |
| Concurrency control | Not publicly documented in depth (SaaS internals) | Atomic primitive (Redis SETNX/Lua or conditional DB UPDATE) + short TTL hold, 3-state lifecycle | Adopt the 3-state lifecycle (available/held/booked) and require the storage protocol to expose an atomic conditional-write primitive; no Redis dependency in v1, SQL row-locking plays the same role |
| Hold expiry | Calendly/Cal.com don't expose a public "hold" concept (bookings are typically direct) | TTL-based, store-enforced (Redis expiry), lazy rather than actively swept in the leanest designs | Lazy-on-read TTL expiry, matching PROJECT.md's explicit "no background sweeper" decision |
| Recurrence | Both fully support recurring event types as a core product feature | N/A (events are one-off) | Deliberately deferred — a SaaS product needs recurrence on day one, a v1 library serving one contract-first consumer does not |
| Domain coupling | Both are domain-specific products (meeting scheduling) with named concepts ("event type," "host") | Domain-specific (seats, venues, events) | This engine is the odd one out by design — zero domain vocabulary, so it generalizes across escape rooms, salons, restaurants, etc. — a genuine differentiator versus every comparable system found |

## Sources

- [Solving Double Booking At Scale: 7 Patterns (Airbnb, Calendly, Stripe)](https://medium.com/@the_atomic_architect/solving-double-booking-at-scale-7-battle-tested-patterns-from-airbnb-calendly-and-stripe-b7739ca5c9b4) — MEDIUM confidence (cross-checked against multiple system-design sources on idempotency/TTL/atomic patterns)
- [Design a Ticket Booking Site Like Ticketmaster (hellointerview.com)](https://www.hellointerview.com/learn/system-design/problem-breakdowns/ticketmaster) — MEDIUM confidence
- [Ticketmaster System Design (systemdesignschool.io)](https://systemdesignschool.io/problems/ticketmaster/solution) — MEDIUM confidence
- [Idempotency in APIs: Designing for Predictability and Safety](https://thearchitectsnotebook.substack.com/p/idempotency-in-apis-designing-for) — MEDIUM confidence
- [Cal.com API docs / open-source scheduling overview](https://dev.to/0012303/calcom-has-a-free-api-open-source-scheduling-that-replaces-calendly-nim) — LOW confidence (secondary/blog source, not official docs; not independently verified against Cal.com's own API reference in this pass)
- [Calendly Calendar Availability and Free/Busy Status Guide](https://community.calendly.com/asked-answered-79/calendly-calendar-availability-and-free-busy-status-guide-4885) — LOW confidence (community forum, not official docs)
- [pyschedule — resource-constrained scheduling in Python](https://github.com/timnon/pyschedule) — LOW confidence (single GitHub project page, not cross-checked)
- [dateutil rrule documentation](https://dateutil.readthedocs.io/en/stable/rrule.html) — MEDIUM confidence (official library docs)
- PROJECT.md and README.md (this repository) — HIGH confidence (primary source, author-authored project scope)

---
*Feature research for: domain-agnostic Python availability/scheduling engine library*
*Researched: 2026-09-02*
