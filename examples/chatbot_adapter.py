"""Reference AvailabilityPort adapter — NOT part of the installed package (D-03).

This is the ONE file in this repo allowed to import `chatbot_engine`. CLAUDE.md's
one-way dependency rule ("engine imports no consumer") applies to
`src/availability_engine/` — this module lives outside that tree specifically so
it structurally cannot violate the rule; the shipped wheel never imports or
depends on `chatbot_engine`.

Demonstrates satisfying the consumer's synchronous `AvailabilityPort` contract
using this engine's `SyncAvailabilityEngine` (D-04). A real consumer either
copies this file into their own composition root or imports it directly as a
worked example — it is proven end to end by
`tests/integration/test_chatbot_conformance.py` (and
`tests/integration/test_chatbot_conformance_sql.py`'s SQLStore-backed variant)
subclassing the consumer's `AvailabilityContractSuite`, but is not itself a
separately-versioned public API.

D-09 (Plan 26-11): this file is a verbatim resync of the sibling
`SocialNetwork-Chatbot` repo's canonical
`src/chatbot_engine/availability/engine_adapter.py` (the direction D-09
mandates — that repo authors the spec this engine implements, never the
reverse). The only intentional deviation from that file's content is this
module docstring's own framing paragraph, which describes this file's role
from THIS (reference-adapter) repo's point of view rather than the promoted,
in-core copy's point of view.

Idempotency-key bookkeeping (`self._hold_keys` / `self._confirmed_keys`) exists
to close a semantics gap between the engine's own idempotency guarantee (a
same-key retry of `place_hold` re-checks live capacity and would otherwise
surface a misleading `CapacityExhaustedError`/`SlotUnavailable` if the original
hold was already confirmed into a booking) and the consumer's richer contract,
which requires that exact retry to raise `HoldConflict` instead (see
`AvailabilityPort.place_hold`'s docstring).

Every id this adapter surfaces (`hold_id`/`booking_id`/`confirmation_ref`) is
the engine's own already-`uuid4()`-generated id, verbatim — never a freshly
minted or predictable value (T-05-05). `confirm_hold` reuses `booking.id` as
both `booking_id` and `confirmation_ref`, which is what makes all three bearer
tokens for a given reservation resolve to the same underlying value, and is
what makes `cancel(ref)` work uniformly regardless of which token the caller
holds.

Exception translation never interpolates `details`/payload content into a
raised consumer exception's message (T-05-06, mirrors `errors.py`'s T-01-01
no-payload-in-constructor rule) — every re-raise below carries no message.

WR-03 (code review, Phase 7): every `availability_engine.*` import is lazy,
function-scoped (never module top-level) -- mirrors `mapping.py`/
`engine_bootstrap.py`'s convention (itself mirroring
`chatbot_engine.persistence.reconcile.bootstrap_booking_core`'s local
`alembic` import) -- so `chatbot_engine` (and this now-core, promoted module
in particular, per D-03) keeps importing cleanly with no `[availability]`
extra installed (PKG-02). `SyncAvailabilityEngine` is used only as a type
hint (`from __future__ import annotations` makes that a lazily-evaluated
string), so it lives behind `TYPE_CHECKING` rather than a function-scoped
import.

Phase 26 (ENGINE-04/D-08, Plan 26-05) widens `query_availability`/
`place_hold` with an optional, keyword-only `business_id` kwarg, forwarded
to the real engine ONLY when explicitly supplied (never as an explicit
`None`, which the currently-pinned v0.1.0 engine would reject with
`TypeError` since it declares no such parameter at all). `self._hold_keys`/
`self._confirmed_keys` are rekeyed from bare `idempotency_key` strings to
`(business_id, idempotency_key)` tuples so two tenants' identical
`idempotency_key` strings never collide on a shared adapter instance.
`confirm_hold`/`cancel` are DELIBERATELY left untouched and take no
`business_id` parameter anywhere in this phase (D-08 design rule, restated
identically in `port.py`/`stub.py`/the sibling engine's own `storage`
layer): both already operate on an already globally-unique `uuid4` bearer
token, and any tenant-scoped isolation they need is derived internally from
the row that token resolves to, never from a caller-supplied `business_id`
-- this is the one coherent rule that keeps the port/adapter/engine-facade/
storage-protocol layers from diverging into incompatible tenancy models.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from chatbot_engine.availability.port import (
    AvailabilityPort,
    HoldConflict,
    HoldExpired,
    ResourceDefinition,
    SlotUnavailable,
)
from chatbot_engine.availability.port import (
    Booking as ConsumerBooking,
)
from chatbot_engine.availability.port import (
    Hold as ConsumerHold,
)
from chatbot_engine.availability.port import (
    Slot as ConsumerSlot,
)

if TYPE_CHECKING:
    from availability_engine.sync import SyncAvailabilityEngine


def _translate_resource_definition(resource: ResourceDefinition) -> dict[str, Any]:
    """Pure shape translation from a repo-owned ``ResourceDefinition`` to the
    agreed v0.2 engine ``Resource`` field names -- plain dicts/ints/strings/
    datetimes only, ZERO ``availability_engine`` imports anywhere in this
    function's body (D-09, this phase's RESEARCH.md Patterns 1/3/4).

    This is what makes the translation logic unit-testable in isolation,
    against a base install with no ``[availability]`` extra, independent of
    whether the installed ``availability-engine`` package has landed v0.2's
    types yet -- ``define_resource`` below still needs its own lazy,
    v0.2-only import for the actual ``Resource``/``BlockInterval``/
    ``LocalInterval``/``Weekday`` construction, which this function
    deliberately never touches.
    """
    return {
        "id": resource.resource_id,
        "business_id": resource.business_id,
        "capacity": resource.units,
        "operating_hours": {
            weekday: [{"start": h.start, "end": h.end} for h in hours]
            for weekday, hours in resource.operating_hours.items()
        },
        "blocks": [{"start": b.start, "end": b.end} for b in resource.blocks],
        "buffer_minutes": resource.buffer_minutes,
        "timezone": resource.timezone,
        "slot_duration_minutes": resource.slot_duration_minutes,
    }


def _encode_slot_id(resource_id: str, start: datetime, end: datetime) -> str:
    """Encode a real-engine slot's identity as an opaque ``slot_id`` string.

    Shared by ``query_availability`` and ``find_openings`` so both methods'
    returned ``Slot.slot_id`` values round-trip identically through
    ``place_hold``'s inverse ``json.loads`` -- see ``query_availability``'s
    own docstring-level WR-03 note for why ``json.dumps`` (not an unescaped
    ``"|"``-joined string) is used here.
    """
    return json.dumps([resource_id, start.isoformat(), end.isoformat()])


def close_availability_engine(port: object) -> None:
    """Tear down a real, ``AvailabilityEngineAdapter``-shaped ``port``'s
    daemon background thread AND dispose the SQLAlchemy ``AsyncEngine``
    backing its SQL-backed ``SQLStore`` -- a no-op for any ``port`` shape
    that doesn't carry an ``_engine``/``close`` pair (e.g. the in-repo
    stub), and skips the dispose step (but still stops the thread) for an
    adapter backed by ``InMemoryStore``, which has no SQL engine at all.

    WR-01 (code review, Phase 7): plain ``sync_engine.close()`` only stops
    the background thread/loop -- it never disposes the ``AsyncEngine``'s
    connection pool, leaving an un-awaited ``aiosqlite`` connection for the
    garbage collector to warn about (this repo's ``filterwarnings =
    ["error"]`` turns that warning into a hard failure in tests; in
    production it is a real, silent connection leak). Dispose MUST run on
    the SAME background loop that opened those connections (asyncio
    connections are not safely closeable from a different thread/loop), so
    it is scheduled via ``run_coroutine_threadsafe`` and awaited to
    completion BEFORE ``close()`` stops that loop.

    This is now the ONE copy of this teardown logic, called from production
    (``consumers.escaperoom.asgi._close_availability_engine``) and both
    real-engine test suites (``tests/consumers/test_build_runtime.py``,
    ``tests/consumers/test_availability_engine_conformance.py``) --
    replacing three previously-divergent copies where only the two test
    copies correctly disposed the ``AsyncEngine``.

    WR-05: every hop below reaches through an undocumented PRIVATE
    attribute of the sibling ``availability-engine`` package (``_engine``/
    ``_storage``/``_loop``) -- there is no public teardown API for this
    today. A future ``availability-engine`` release could rename any of
    these and this function would then silently skip the dispose step
    again, quietly reintroducing the exact connection leak this function
    exists to close. To make that discoverable rather than silent, this
    logs a ``structlog`` warning for the hops that are expected to resolve
    on EVERY ``SyncAvailabilityEngine`` regardless of storage backend
    (``_engine``, ``_loop``) -- unlike ``storage._engine`` itself, which is
    legitimately absent for an ``InMemoryStore``-backed engine (no SQL
    engine to dispose) and is therefore NOT warning-worthy on its own.

    26-05 (cluster-6 review, moved here from Plan 26-13): a
    ``_BusinessScopedPort`` (``AvailabilityPort.scoped()``, Plan 26-01) wraps
    any ``AvailabilityPort`` via a private ``_delegate`` attribute, not
    ``_engine`` -- this function would otherwise silently no-op on a scoped
    real adapter and leak its connection/thread. Unwrapped FIRST, via an
    ``isinstance``-guarded (not generic ``hasattr(port, "_delegate")``) loop
    so this can never unwrap an unrelated object that happens to carry a
    same-named attribute for some other reason, and terminates
    deterministically even if a future scoping nests one
    ``_BusinessScopedPort`` inside another.
    """
    import structlog

    from chatbot_engine.availability.port import _BusinessScopedPort

    while isinstance(port, _BusinessScopedPort):
        port = port._delegate

    sync_engine = getattr(port, "_engine", None)
    if sync_engine is None or not hasattr(sync_engine, "close"):
        return
    logger = structlog.get_logger()
    domain_engine = getattr(sync_engine, "_engine", None)
    if domain_engine is None:
        logger.warning(
            "availability_engine.teardown_attribute_missing",
            attribute="_engine",
            hint="SyncAvailabilityEngine no longer exposes ._engine -- "
            "dispose step skipped, connection leak likely",
        )
    storage = getattr(domain_engine, "_storage", None)
    if domain_engine is not None and storage is None:
        logger.warning(
            "availability_engine.teardown_attribute_missing",
            attribute="_storage",
            hint="the domain engine no longer exposes ._storage -- "
            "dispose step skipped, connection leak likely",
        )
    sql_engine = getattr(storage, "_engine", None)
    loop = getattr(sync_engine, "_loop", None)
    if loop is None:
        logger.warning(
            "availability_engine.teardown_attribute_missing",
            attribute="_loop",
            hint="SyncAvailabilityEngine no longer exposes ._loop -- "
            "dispose step skipped, connection leak likely",
        )
    if sql_engine is not None and hasattr(sql_engine, "dispose") and loop is not None:
        future = asyncio.run_coroutine_threadsafe(sql_engine.dispose(), loop)
        future.result(timeout=5)
    sync_engine.close()


class AvailabilityEngineAdapter(AvailabilityPort):
    """Satisfies `AvailabilityPort` by wrapping a `SyncAvailabilityEngine`."""

    def __init__(self, engine: SyncAvailabilityEngine) -> None:
        self._engine = engine
        # (business_id, idempotency_key) -> the hold_id place_hold produced.
        # Rekeyed to a tuple (26-05, ENGINE-04/D-08) so two tenants'
        # identical idempotency_key strings never collide on a shared
        # adapter instance -- confirm_hold's own loop below treats this key
        # opaquely, so widening it from a bare str needs no logic change
        # there.
        self._hold_keys: dict[tuple[str | None, str], str] = {}
        # (business_id, idempotency_key) pairs whose hold has since been
        # confirmed into a booking — distinguishes "genuinely
        # capacity-exhausted retry" from "retry whose original hold was
        # already confirmed" in place_hold's exception-translation below.
        self._confirmed_keys: set[tuple[str | None, str]] = set()
        # WR-02: guards both dicts/sets above. This adapter crosses a
        # thread boundary via SyncAvailabilityEngine, and its own
        # docstring presents it as a copyable production template where a
        # ConversationService may call place_hold/confirm_hold from
        # multiple threads/tasks against the same adapter instance.
        self._keys_lock = threading.Lock()

    def query_availability(
        self,
        resource_type: str,
        window: tuple[datetime, datetime],
        party_size: int,
        *,
        business_id: str | None = None,
    ) -> list[ConsumerSlot]:
        # v1: single-mapping — resource_type IS the engine's resource_id
        # verbatim, no separate type->id lookup layer.
        # 26-05/ENGINE-04/D-08: business_id is OMITTED from the forwarded
        # call entirely when None -- the currently-pinned v0.1.0 engine
        # declares no `business_id` parameter at all, so forwarding it as an
        # explicit None would raise TypeError. Only Plan 26-13's v0.2-
        # repinned engine accepts this kwarg.
        result = (
            self._engine.get_availability(  # type: ignore[call-arg]
                resource_type, window[0], window[1], business_id=business_id
            )
            if business_id is not None else
            self._engine.get_availability(resource_type, window[0], window[1])
        )
        slots: list[ConsumerSlot] = []
        for s in result.available:
            if s.remaining < party_size:
                continue
            # Encodes both start AND end (unlike a naive start-only
            # encoding) — place_hold below needs the end time too.
            # WR-03: json.dumps (not an unescaped "|"-joined string) so a
            # resource_id containing "|" (a plausible domain-injected id,
            # since the engine names zero domain concepts and imposes no
            # character restriction on Resource.id) can never desync the
            # inverse split() in place_hold below. Extracted into
            # `_encode_slot_id` (26-05) so `find_openings` reuses the exact
            # same encoding rather than duplicating it.
            slot_id = _encode_slot_id(s.resource_id, s.start, s.end)
            slots.append(
                ConsumerSlot(
                    slot_id=slot_id,
                    resource_id=s.resource_id,
                    starts_at=s.start,
                    ends_at=s.end,
                    capacity=s.remaining,
                )
            )
        return slots

    def place_hold(
        self,
        slot_id: str,
        ttl_seconds: int,
        idempotency_key: str,
        *,
        business_id: str | None = None,
    ) -> ConsumerHold:
        # CR-01: must be checked BEFORE calling the engine at all. The
        # underlying engine only raises on a post-confirm retry when the
        # slot's capacity is *still* exhausted (memory.py's fresh
        # capacity re-check on a missing/consumed Hold) -- for a
        # capacity>1 resource, a confirmed Booking occupies only one
        # unit, so the fresh check can succeed and silently mint a
        # brand-new Hold instead of raising. Checking here makes the
        # behavior independent of live capacity, matching
        # AvailabilityPort.place_hold's documented contract.
        # WR-03: lazy import -- see module docstring.
        from availability_engine.errors import (
            CapacityExhaustedError,
            IdempotencyConflictError,
            OutsideHoursError,
            ResourceNotFoundError,
        )

        with self._keys_lock:
            if (business_id, idempotency_key) in self._confirmed_keys:
                raise HoldConflict()
        # WR-03: inverse of the json.dumps encoding above -- correctly
        # round-trips a resource_id containing any character, including
        # "|", unlike the old unescaped "|".split("|").
        # UF-1: slot_id is an unauthenticated bearer capability token --
        # a malformed/truncated/tampered value (not JSON, not a 3-element
        # list, or non-ISO date strings) must translate to the typed
        # SlotUnavailable the AvailabilityPort contract guarantees for
        # this method, not a raw JSONDecodeError/ValueError/TypeError.
        try:
            resource_id, start_iso, end_iso = json.loads(slot_id)
            start = datetime.fromisoformat(start_iso)
            end = datetime.fromisoformat(end_iso)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise SlotUnavailable() from exc
        try:
            # 26-05/ENGINE-04/D-08: same None-omission pattern as
            # query_availability above -- the v0.1.0-pinned engine's
            # place_hold declares no business_id parameter at all.
            hold = (
                self._engine.place_hold(  # type: ignore[call-arg]
                    resource_id,
                    start,
                    end,
                    ttl_seconds,
                    idempotency_key=idempotency_key,
                    business_id=business_id,
                )
                if business_id is not None else
                self._engine.place_hold(
                    resource_id,
                    start,
                    end,
                    ttl_seconds,
                    idempotency_key=idempotency_key,
                )
            )
        except (
            CapacityExhaustedError,
            OutsideHoursError,
            ResourceNotFoundError,
        ) as exc:
            # The post-confirm-retry case is now fully handled by the
            # `_confirmed_keys` check above, before the engine is ever
            # called -- reaching this except block means the key was
            # never confirmed, so a genuine capacity/hours/resource
            # failure always translates to SlotUnavailable.
            raise SlotUnavailable() from exc
        except IdempotencyConflictError as exc:
            # Reused key for a genuinely different slot.
            raise HoldConflict() from exc
        if idempotency_key:
            with self._keys_lock:
                self._hold_keys[(business_id, idempotency_key)] = hold.id
        return ConsumerHold(
            hold_id=hold.id, slot_id=slot_id, expires_at=hold.expires_at
        )

    def confirm_hold(self, hold_id: str, details: dict[str, str]) -> ConsumerBooking:
        # WR-03: lazy import -- see module docstring.
        from availability_engine.errors import HoldExpiredError, HoldNotFoundError

        try:
            # Passing hold_id itself as the engine's own idempotency key is
            # what gives "repeated confirm_hold(same hold_id) returns the
            # SAME booking" for free, via the engine's existing
            # fingerprint-based idempotency (same hold_id + same details ->
            # same fingerprint -> cached replay).
            booking = self._engine.confirm_hold(
                hold_id, dict(details), idempotency_key=hold_id
            )
        except (HoldExpiredError, HoldNotFoundError) as exc:
            raise HoldExpired() from exc
        with self._keys_lock:
            for key, produced_hold_id in self._hold_keys.items():
                if produced_hold_id == hold_id:
                    self._confirmed_keys.add(key)
        return ConsumerBooking(
            booking_id=booking.id,
            # WR-03: same json.dumps encoding as query_availability's
            # slot_id above, for consistency (this value is opaque to the
            # consumer and never re-parsed in this file, but keeping one
            # encoding scheme avoids reintroducing the unescaped-"|" bug
            # if that ever changes).
            slot_id=json.dumps(
                [
                    booking.resource_id,
                    booking.slot_start.isoformat(),
                    booking.slot_end.isoformat(),
                ]
            ),
            # Reuses the engine's own already-uuid4() booking.id (which,
            # per storage/memory.py, equals the original hold.id) as BOTH
            # booking_id and confirmation_ref, rather than minting a fresh
            # uuid — this is what makes all three bearer tokens the same
            # underlying value for a given reservation.
            confirmation_ref=booking.id,
        )

    def cancel(self, ref: str) -> None:
        # WR-03: lazy import -- see module docstring.
        from availability_engine.errors import (
            BookingNotFoundError as EngineBookingNotFoundError,
        )

        try:
            self._engine.cancel_booking(ref)
            return
        except EngineBookingNotFoundError:
            pass
        # Idempotent no-op on any unknown or non-hold id.
        self._engine.release_hold(ref)

    def define_resource(self, resource: ResourceDefinition) -> None:
        """Translate ``resource`` into the real engine's native ``Resource``
        shape and upsert it (D-09, Plan 26-05).

        Written NOW, against the AGREED v0.2 engine API shape this phase's
        RESEARCH.md specifies (Patterns 1/3/4) — per D-09, this file is the
        CANONICAL source the sibling repo's own v0.2 implementation effort
        reads as its spec. The real ``availability-engine`` is still pinned
        at v0.1.0 (pre-v0.2 contract) as of this plan, so the lazy import
        below is NOT expected to succeed yet (v0.1.0's ``contracts.py`` has
        no ``BlockInterval``) — this method is not exercisable until Plan
        26-13's repin, by design (see 26-05-PLAN.md's "Speculative-
        verification note"). The pure shape translation it depends on
        (``_translate_resource_definition``) is proven correct in isolation,
        independent of this import, today.
        """
        translated = _translate_resource_definition(resource)
        # WR-03-style lazy import: see module docstring. Genuinely requires
        # the v0.2-shaped package; not expected to succeed against v0.1.0.
        # mypy: BlockInterval does not exist in the currently-pinned v0.1.0
        # `contracts.py` -- this is the exact, accepted, documented
        # pre-repin gap this method's docstring and 26-05-PLAN.md's
        # "Speculative-verification note" describe. Resolved for real by
        # Plan 26-13's repin, never before.
        from availability_engine.contracts import (  # type: ignore[attr-defined]
            BlockInterval,
            LocalInterval,
            Resource,
            Weekday,
        )

        operating_hours: dict[Weekday, list[LocalInterval]] = {
            Weekday(weekday): [
                LocalInterval(start=h["start"], end=h["end"]) for h in hours
            ]
            for weekday, hours in translated["operating_hours"].items()
        }
        blocks = [
            BlockInterval(start=b["start"], end=b["end"])
            for b in translated["blocks"]
        ]
        engine_resource = Resource(
            id=translated["id"],
            business_id=translated["business_id"],
            capacity=translated["capacity"],
            operating_hours=operating_hours,
            buffer=timedelta(minutes=translated["buffer_minutes"]),
            timezone=translated["timezone"],
            slot_duration=timedelta(minutes=translated["slot_duration_minutes"]),
            blocks=blocks,
        )
        self._engine.define_resource(engine_resource)

    def find_openings(
        self,
        business_id: str,
        resource_id: str,
        window: tuple[datetime, datetime],
        duration_minutes: int,
    ) -> list[ConsumerSlot]:
        """Search the real engine for duration-aware openings (D-09, Plan
        26-05) — see ``define_resource``'s docstring above for why this
        method is written against the agreed v0.2 shape but not exercisable
        until Plan 26-13's repin.

        An unknown ``(business_id, resource_id)`` pair returns an empty list
        (never raises), matching ``InMemoryAvailabilityStub.find_openings``'s
        contract — consistency across both ``AvailabilityPort``
        implementations.
        """
        # WR-03-style lazy import: see module docstring.
        from availability_engine.errors import ResourceNotFoundError

        try:
            # mypy: `duration`/`business_id` are not parameters of the
            # currently-pinned v0.1.0 `SyncAvailabilityEngine.get_availability`
            # -- the same accepted pre-repin gap as `define_resource` above.
            # Resolved for real by Plan 26-13's repin, never before.
            result = self._engine.get_availability(  # type: ignore[call-arg]
                resource_id,
                window[0],
                window[1],
                duration=timedelta(minutes=duration_minutes),
                business_id=business_id,
            )
        except ResourceNotFoundError:
            return []
        return [
            ConsumerSlot(
                slot_id=_encode_slot_id(s.resource_id, s.start, s.end),
                resource_id=s.resource_id,
                starts_at=s.start,
                ends_at=s.end,
                capacity=s.remaining,
            )
            for s in result.available
        ]
