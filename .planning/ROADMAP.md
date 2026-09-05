# Roadmap: availability-engine

## Milestones

- ✅ **v1.0 — v1 Release** — Phases 1–5 (shipped 2026-09-05)

## Phases

<details>
<summary>✅ v1.0 — v1 Release (Phases 1–5) — SHIPPED 2026-09-05</summary>

Full detail archived in [`milestones/v1.0-ROADMAP.md`](milestones/v1.0-ROADMAP.md).
Requirements: [`milestones/v1.0-REQUIREMENTS.md`](milestones/v1.0-REQUIREMENTS.md).
Audit: [`milestones/v1.0-MILESTONE-AUDIT.md`](milestones/v1.0-MILESTONE-AUDIT.md).

- [x] Phase 1: End-to-End Walking Skeleton (In-Memory) (3/3 plans) — completed 2026-09-03
- [x] Phase 2: Capacity & Time Correctness (3/3 plans) — completed 2026-09-04
- [x] Phase 3: Idempotency & Cancellation (2/2 plans) — completed 2026-09-04
- [x] Phase 4: SQL Backend & Concurrency Proof (4/4 plans) — completed 2026-09-04
- [x] Phase 5: Packaging, Docs & v1 Release (5/5 plans) — completed 2026-09-05

Shipped: a domain-agnostic Python scheduling library — importable `AvailabilityEngine`
(async) + `SyncAvailabilityEngine` bridge over a coarse-grained async `StorageBackend`
protocol, with `InMemoryStore` and a SQLite+Postgres `SQLStore` swapping in invisibly;
capacity-aware, DST/midnight-crossing-correct, lazy hold expiry, reason codes, idempotency
keys, cancellation, a frozen documented output contract, a real-Postgres no-overbook
concurrency proof, and a `v0.1.0` git tag the first consumer repins to.

</details>
