# availability-engine

Reusable **calendar / availability engine** — a generic scheduling library that models
**resources × time-slots × holds** and emits **structured available / booked outputs**. Names
zero domain concepts (no "room", "escape", "appointment"): the domain is injected by the consumer.

> **Status:** scaffold only. Planning not started — run `/gsd-new-project` in this directory to
> grow the full `.planning/` (PROJECT.md, requirements, roadmap). This README is the seed brief.

## Why it exists

A booking assistant needs to answer two questions safely and deterministically:

1. **What's available?** — given resources (each with capacity, operating hours, and buffers) and
   existing bookings, compute open slots.
2. **Can I take this slot, atomically?** — place a short-lived **hold** so two concurrent bookers
   can't grab the same slot, then confirm or release it.

General calendars (e.g. Google Calendar) model *events on a calendar*, not *resources with
capacity and atomic holds* — so this engine owns that model directly and can treat an external
calendar as an optional sync/export adapter later.

## Core model (initial sketch — to be refined during planning)

- **Resource** — a bookable thing with capacity, operating hours, and reset/buffer time between
  sessions (e.g. an escape room, a chair, a table — the *consumer* names it).
- **Slot** — a resource + a time window; has a computed state (`available` / `held` / `booked`).
- **Hold** — a short-lived, atomic reservation on a slot pending confirmation (TTL, then auto-release).
- **Booking** — a confirmed hold, with the consumer's party/contact payload attached opaquely.
- **Query outputs** — structured availability (`available` / `booked` windows) the consumer renders.

## Ecosystem placement

Part of the `~/Projects/Reusable/` hub-and-spoke ecosystem (see `~/.claude/context/deps/`).

- **Kind:** Python 3.12+ library, `uv` + `hatchling`, consumed via **git-tag pin** (uv source),
  matching the `YahirReusableBot` convention. Public GitHub by default.
- **First consumer:** [`SocialNetwork-Chatbot`](https://github.com/Ygaray) — the reusable booking
  chatbot backend. Built **contract-first**: the chatbot codes against this engine's structured
  contract (stubbed) while this lib is built in parallel.
- **One-way dependency:** consumers import this engine; this engine imports no consumer and names
  no consumer's domain.

## Next step

```bash
cd ~/Projects/Reusable/availability-engine
# start its own GSD project — this README is the seed context
/gsd-new-project
```
