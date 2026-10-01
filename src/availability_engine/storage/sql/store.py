"""SQLStore — a faithful SQL port of memory.py's StorageBackend, backed by
SQLAlchemy Core against either SQLite (`sqlite+aiosqlite`) or Postgres
(`postgresql+asyncpg`).

Design note: only `place_hold` acquires the dialect-aware lock (see
`locking.py`). `confirm_hold`, `release_hold`, and `cancel_booking` each act
on a single already-existing row (an UPDATE or DELETE addressed by primary
key), which Postgres's normal READ COMMITTED row-level atomicity already
handles correctly — the phantom-insert race RESEARCH.md identified is
specific to `place_hold`'s check-a-count-then-insert-a-row-that-does-not-
yet-exist shape. D-04's isolation level (READ COMMITTED) is preserved
everywhere; no SERIALIZABLE/retry-loop is introduced anywhere in this
backend.

26-09-PLAN.md Task 1 (D-08/ENGINE-04): `get_resource`/`get_active_entries`/
`place_hold` are business_id-scoped as an explicit first parameter —
structurally, a query for one tenant's resource/holds/bookings cannot
return another tenant's row. `save_resource` derives its namespace from
`resource.business_id` (the object already carries it); `confirm_hold`/
`release_hold`/`cancel_booking` take no business_id at all (D-A) — see
`storage/protocol.py`'s module docstring for the full three-way split.

26-09-PLAN.md Task 2 (D-05): `place_hold`'s capacity check uses
`peak_concurrency` against symmetrically buffer-padded busy intervals,
fetched over a buffer-widened window, and the Postgres advisory lock is
widened to `(business_id, resource_id)` — see that function's call site
below and `locking.py` for the full rationale.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Row, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from availability_engine.contracts import Booking, BookingStatus, Hold, Resource
from availability_engine.core.availability import peak_concurrency
from availability_engine.core.intervals import Interval
from availability_engine.errors import (
    BookingNotFoundError,
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
    IdempotencyConflictError,
)
from availability_engine.storage._shared import _fingerprint
from availability_engine.storage.sql import models
from availability_engine.storage.sql.locking import (
    acquire_postgres_slot_lock,
    attach_sqlite_begin_immediate,
)


def _ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime read back from either dialect to UTC-aware.

    SQLite's DATETIME type drops tzinfo on round-trip (rows come back
    naive); Postgres's `DateTime(timezone=True)` round-trips aware. Every
    write in this backend is already UTC-aware wall-clock at construction
    time (`UtcDatetime` enforcement upstream), so a naive read value's
    wall-clock fields ARE already UTC — attach the label rather than
    convert.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hold_from_row(row: Row[Any]) -> Hold:
    return Hold(
        id=row.id,
        resource_id=row.resource_id,
        slot_start=_ensure_utc(row.slot_start),
        slot_end=_ensure_utc(row.slot_end),
        expires_at=_ensure_utc(row.expires_at),
    )


def _booking_from_row(row: Row[Any]) -> Booking:
    return Booking(
        id=row.id,
        resource_id=row.resource_id,
        slot_start=_ensure_utc(row.slot_start),
        slot_end=_ensure_utc(row.slot_end),
        payload=row.payload,
        status=BookingStatus(row.status),
    )


@dataclass(frozen=True, slots=True)
class _IdempotencyRow:
    fingerprint: str
    result_type: str
    result_id: str


class SQLStore:
    """Implements `StorageBackend` (structurally, via `Protocol`) against a
    SQLAlchemy `AsyncEngine` — SQLite or Postgres, dialect branch confined to
    `locking.py`."""

    def __init__(self, engine: AsyncEngine) -> None:
        # CR-02: SQLite's write-serialization fix (BEGIN IMMEDIATE) is what
        # makes place_hold phantom-safe on SQLite — wire it in here so the
        # "obvious" construction path (`SQLStore(create_async_engine(...))`)
        # is safe by default, rather than requiring every consumer to
        # discover and call `attach_sqlite_begin_immediate` themselves.
        # Idempotent (see locking.py) — safe even if the caller (or a test
        # fixture) already attached it, and safe across the many SQLStore
        # instances typically constructed against one shared engine.
        if engine.sync_engine.dialect.name == "sqlite":
            attach_sqlite_begin_immediate(engine)
        self._engine = engine

    # -- Resource CRUD --------------------------------------------------

    async def save_resource(self, resource: Resource) -> None:
        # 26-09-PLAN.md Task 1: business_id is NOT a separate parameter —
        # derived internally from resource.business_id, the object already
        # carries it (Protocol Consistency note, closes review's HIGH
        # "save_resource protocol shape is inconsistent").
        business_id = resource.business_id
        definition = resource.model_dump(mode="json")
        async with self._engine.begin() as conn:
            existing_id = await conn.scalar(
                select(models.resources.c.id).where(
                    models.resources.c.business_id == business_id,
                    models.resources.c.id == resource.id,
                )
            )
            if existing_id is None:
                # WR-01: two concurrent save_resource(resource) calls for a
                # not-yet-persisted (business_id, id) pair can both observe
                # existing_id is None and both attempt the INSERT branch.
                # Scope the INSERT to a SAVEPOINT (mirrors
                # _write_idempotency_record's pattern below) so a losing
                # writer's IntegrityError doesn't abort the whole enclosing
                # transaction on Postgres, and fall back to UPDATE on
                # conflict rather than surfacing a raw driver-level error.
                try:
                    async with conn.begin_nested():
                        await conn.execute(
                            insert(models.resources).values(
                                id=resource.id,
                                business_id=business_id,
                                definition=definition,
                            )
                        )
                except IntegrityError:
                    await conn.execute(
                        update(models.resources)
                        .where(
                            models.resources.c.business_id == business_id,
                            models.resources.c.id == resource.id,
                        )
                        .values(definition=definition)
                    )
            else:
                await conn.execute(
                    update(models.resources)
                    .where(
                        models.resources.c.business_id == business_id,
                        models.resources.c.id == resource.id,
                    )
                    .values(definition=definition)
                )

    async def get_resource(self, business_id: str, resource_id: str) -> Resource | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(models.resources.c.definition).where(
                        models.resources.c.business_id == business_id,
                        models.resources.c.id == resource_id,
                    )
                )
            ).first()
        if row is None:
            return None
        # 26-09-PLAN.md Task 1 (closes review's HIGH "resources.definition is
        # not updated"): ALWAYS override the validated object's business_id
        # with the authoritative COLUMN value it was fetched by. A
        # pre-migration row's `definition` JSON lacks a business_id key and
        # would otherwise validate to Pydantic's own default sentinel, which
        # could disagree with the column's real value — this override makes
        # that disagreement structurally impossible regardless of what the
        # JSON blob says.
        return Resource.model_validate(row.definition).model_copy(
            update={"business_id": business_id}
        )

    # -- Active-entries primitive (AVAIL-03) -----------------------------

    async def get_active_entries(
        self, business_id: str, resource_id: str, window: Interval
    ) -> list[Hold | Booking]:
        async with self._engine.connect() as conn:
            return await self._get_active_entries(
                conn, business_id, resource_id, window
            )

    async def _get_active_entries(
        self,
        conn: AsyncConnection,
        business_id: str,
        resource_id: str,
        window: Interval,
    ) -> list[Hold | Booking]:
        # AVAIL-03/HOLD-05: the ONE shared, expiry-filtering active-entries
        # primitive — both the public Protocol method and place_hold's
        # capacity check call this, never a second, duplicate scan.
        now = datetime.now(UTC)
        entries: list[Hold | Booking] = []
        hold_rows = (
            await conn.execute(
                select(models.holds).where(
                    models.holds.c.business_id == business_id,
                    models.holds.c.resource_id == resource_id,
                    models.holds.c.expires_at > now,
                    # Half-open overlap predicate, matching
                    # core/intervals.py's overlaps() semantics exactly.
                    models.holds.c.slot_start < window.end,
                    window.start < models.holds.c.slot_end,
                )
            )
        ).all()
        entries.extend(_hold_from_row(row) for row in hold_rows)

        booking_rows = (
            await conn.execute(
                select(models.bookings).where(
                    models.bookings.c.business_id == business_id,
                    models.bookings.c.resource_id == resource_id,
                    models.bookings.c.status != BookingStatus.CANCELLED.value,
                    models.bookings.c.slot_start < window.end,
                    window.start < models.bookings.c.slot_end,
                )
            )
        ).all()
        entries.extend(_booking_from_row(row) for row in booking_rows)
        return entries

    # -- Idempotency helpers ----------------------------------------------

    async def _get_idempotency_record(
        self, conn: AsyncConnection, business_id: str, operation_type: str, key: str
    ) -> _IdempotencyRow | None:
        row = (
            await conn.execute(
                select(
                    models.idempotency.c.fingerprint,
                    models.idempotency.c.result_type,
                    models.idempotency.c.result_id,
                ).where(
                    models.idempotency.c.business_id == business_id,
                    models.idempotency.c.operation_type == operation_type,
                    models.idempotency.c.key == key,
                )
            )
        ).first()
        if row is None:
            return None
        return _IdempotencyRow(
            fingerprint=row.fingerprint,
            result_type=row.result_type,
            result_id=row.result_id,
        )

    async def _write_idempotency_record(
        self,
        conn: AsyncConnection,
        business_id: str,
        operation_type: str,
        key: str,
        fingerprint: str,
        result_type: str,
        result_id: str,
    ) -> None:
        # A same-key race that slipped past the initial SELECT (rare, but
        # the composite primary key makes it a real possibility even under
        # the lock — e.g. two calls with the SAME key targeting DIFFERENT
        # slots) raises a driver-level IntegrityError. Scope the INSERT
        # attempt to a SAVEPOINT (begin_nested) rather than the outer
        # transaction: on Postgres, an uncaught statement error aborts the
        # *entire* enclosing transaction (every subsequent statement fails
        # until ROLLBACK), so the outer transaction — which may still hold
        # the advisory lock and need to run more statements — must stay
        # usable after this specific INSERT fails.
        try:
            async with conn.begin_nested():
                await conn.execute(
                    insert(models.idempotency).values(
                        business_id=business_id,
                        operation_type=operation_type,
                        key=key,
                        fingerprint=fingerprint,
                        result_type=result_type,
                        result_id=result_id,
                    )
                )
        except IntegrityError:
            existing = await self._get_idempotency_record(
                conn, business_id, operation_type, key
            )
            if existing is None or existing.fingerprint != fingerprint:
                raise IdempotencyConflictError(operation_type, key) from None
            # Fingerprint matches — the racing writer's record already
            # captured this same logical call; this call's own write was
            # simply redundant, nothing further to do.

    # -- Hold / Booking lifecycle -----------------------------------------

    async def place_hold(
        self,
        business_id: str,
        resource_id: str,
        slot: Interval,
        capacity: int,
        ttl_seconds: int,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Hold:
        async with self._engine.begin() as conn:
            if conn.engine.dialect.name == "postgresql":
                # 26-09-PLAN.md Task 2 (closes review's MEDIUM "the advisory
                # lock should include business ID"): widened from Plan
                # 26-07's interim (conn, resource_id) shape to
                # (conn, business_id, resource_id) now that business_id is
                # available at the storage layer — two different tenants'
                # resources sharing a common id string no longer
                # unnecessarily serialize against each other.
                await acquire_postgres_slot_lock(conn, business_id, resource_id)
            # SQLite needs no explicit call — the "begin"-event listener
            # from locking.py already fired for this transaction.

            fp: str | None = None
            if idempotency_key is not None:
                # ttl_seconds is deliberately EXCLUDED from the fingerprint
                # (memory.py Open Question 1) — a legitimate retry may
                # resend a different remaining-timeout budget for the same
                # logical request.
                fp = _fingerprint(resource_id, slot.start, slot.end)
                existing = await self._get_idempotency_record(
                    conn, business_id, "place_hold", idempotency_key
                )
                if existing is not None:
                    if existing.fingerprint != fp:
                        raise IdempotencyConflictError("place_hold", idempotency_key)
                    if existing.result_type != "hold":
                        raise TypeError(
                            "place_hold idempotency record does not reference a Hold"
                        )
                    # CR-01: live-revalidation — never trust the cached
                    # row's snapshot. Fall through to a fresh
                    # check-and-insert if the referenced hold is gone or
                    # expired.
                    live_row = (
                        await conn.execute(
                            select(models.holds).where(
                                models.holds.c.id == existing.result_id
                            )
                        )
                    ).first()
                    if live_row is not None and _ensure_utc(
                        live_row.expires_at
                    ) > datetime.now(UTC):
                        return _hold_from_row(live_row)

            # WR-03: re-read the authoritative capacity from our own store
            # under the transaction/lock rather than trusting the caller-
            # supplied snapshot — closes the race where a concurrent
            # save_resource changes capacity between the caller's read and
            # this lock/transaction acquisition. Fall back to the
            # caller-supplied `capacity` only if the resource isn't tracked
            # here (shouldn't happen via the AvailabilityEngine facade,
            # which already calls get_resource and raises
            # ResourceNotFoundError before ever reaching this storage call —
            # see engine.py's place_hold). This mirrors memory.py's
            # identical fallback and rationale, keeping both backends'
            # behavior in parity for a caller that invokes SQLStore
            # directly, bypassing the facade.
            resource_row = (
                await conn.execute(
                    select(models.resources.c.definition).where(
                        models.resources.c.business_id == business_id,
                        models.resources.c.id == resource_id,
                    )
                )
            ).first()
            resource = (
                Resource.model_validate(resource_row.definition)
                if resource_row is not None
                else None
            )
            effective_capacity = resource.capacity if resource is not None else capacity

            # 26-09-PLAN.md Task 2 Cycle-2 guard (closes review's HIGH
            # "buffer logic dereferences resource.buffer when a resource
            # may be absent"): both backends deliberately support a direct
            # place_hold call against an UNREGISTERED resource using
            # caller-supplied capacity (see
            # test_place_hold_trusts_caller_capacity_for_unregistered_resource)
            # — resolve `buffer` via this `is not None` guard before any use
            # below, never a bare `resource.buffer` attribute access.
            buffer = resource.buffer if resource is not None else timedelta(0)

            # 26-09-PLAN.md Task 2 (D-05, closes review's HIGH "the buffer
            # check cannot retrieve the entries it needs" and "padding only
            # existing entries misses the opposite direction"): fetch over a
            # buffer-WIDENED window on BOTH sides — an existing booking
            # ending shortly before slot.start (or starting shortly after
            # slot.end) does not overlap the unwidened slot at all and would
            # never be retrieved otherwise. Then pad BOTH the existing
            # entries' AND the requested candidate's trailing edge by
            # buffer before the overlap check — for any pair of
            # positive-duration intervals this symmetric check is
            # mathematically equivalent to checking "does the existing
            # entry's padded edge reach into the raw candidate" OR "does
            # the candidate's padded edge reach into the raw existing
            # entry", covering both temporal directions with one check.
            fetch_window = Interval(start=slot.start - buffer, end=slot.end + buffer)
            active = await self._get_active_entries(
                conn, business_id, resource_id, fetch_window
            )
            padded_busy = [
                Interval(start=entry.slot_start, end=entry.slot_end + buffer)
                for entry in active
            ]
            padded_candidate = Interval(start=slot.start, end=slot.end + buffer)
            # D-05: peak_concurrency (the real engine's own proven
            # event-sweep algorithm) replaces a raw len(active) >=
            # effective_capacity count, so a resource with units > 1 and
            # variable-length/overlapping holds is never wrongly rejected
            # or wrongly accepted.
            concurrent_count = peak_concurrency(padded_busy, padded_candidate)
            if concurrent_count >= effective_capacity:
                # Never cache an idempotency record on this failure path —
                # a retry with the same key, after capacity frees up, must
                # be free to succeed. The raised exception carries the
                # UNPADDED slot, never the padded one, since that is what
                # the caller actually requested.
                raise CapacityExhaustedError(resource_id, slot)

            hold_id = str(uuid.uuid4())
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
            await conn.execute(
                insert(models.holds).values(
                    id=hold_id,
                    business_id=business_id,
                    resource_id=resource_id,
                    slot_start=slot.start,
                    slot_end=slot.end,
                    expires_at=expires_at,
                )
            )
            # 26-09-PLAN.md Task 1 (D-A): populate the PERMANENT
            # hold_business_index row in the SAME transaction as the hold
            # itself — this row is never deleted, so confirm_hold can
            # always resolve this hold_id's tenant even long after the
            # hold row is gone.
            await conn.execute(
                insert(models.hold_business_index).values(
                    hold_id=hold_id, business_id=business_id
                )
            )
            hold = Hold(
                id=hold_id,
                resource_id=resource_id,
                slot_start=slot.start,
                slot_end=slot.end,
                expires_at=expires_at,
            )
            if idempotency_key is not None:
                assert fp is not None
                await self._write_idempotency_record(
                    conn,
                    business_id,
                    "place_hold",
                    idempotency_key,
                    fp,
                    "hold",
                    hold_id,
                )
            return hold

    async def confirm_hold(
        self,
        hold_id: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Booking:
        async with self._engine.begin() as conn:
            # 26-09-PLAN.md Task 1 Cycle-2 correction (closes review's HIGH
            # "confirm replay cannot derive the tenant from the hold row"):
            # resolve business_id from the PERMANENT hold_business_index
            # FIRST — before the idempotency check and before any `holds`
            # row lookup. A successful prior confirm_hold already DELETES
            # the holds row, so a replay (second call, same
            # idempotency_key) would find no hold row to derive business_id
            # from if this lookup happened later/elsewhere.
            business_id = await conn.scalar(
                select(models.hold_business_index.c.business_id).where(
                    models.hold_business_index.c.hold_id == hold_id
                )
            )
            if business_id is None:
                # This hold_id was never legitimately placed via
                # place_hold — same "unknown hold" error confirm_hold
                # already raises for a bogus id today. Nothing to be a
                # replay OF, so no idempotency check applies.
                raise HoldNotFoundError(hold_id)

            fp: str | None = None
            if idempotency_key is not None:
                # HOLD-07: mirrors place_hold's idempotency pattern exactly,
                # but this check must come BEFORE the hold-row lookup below
                # — a replay's underlying hold may already have been
                # deleted by the first call's success.
                if payload is not None:
                    try:
                        json.dumps(payload, sort_keys=True)
                    except TypeError as exc:
                        raise TypeError(
                            "confirm_hold payload must be JSON-serializable "
                            "with stable-value semantics for idempotency "
                            "fingerprinting"
                        ) from exc
                fp = _fingerprint(hold_id, payload)
                existing = await self._get_idempotency_record(
                    conn, business_id, "confirm_hold", idempotency_key
                )
                if existing is not None:
                    if existing.fingerprint != fp:
                        raise IdempotencyConflictError("confirm_hold", idempotency_key)
                    if existing.result_type != "booking":
                        raise TypeError(
                            "confirm_hold idempotency record does not "
                            "reference a Booking"
                        )
                    # CR-01: always return the LIVE record (e.g. reflects a
                    # subsequent cancel_booking), never the frozen snapshot.
                    live_row = (
                        await conn.execute(
                            select(models.bookings).where(
                                models.bookings.c.id == existing.result_id
                            )
                        )
                    ).first()
                    if live_row is not None:
                        return _booking_from_row(live_row)
                    raise BookingNotFoundError(existing.result_id)

            hold_row = (
                await conn.execute(
                    select(models.holds).where(models.holds.c.id == hold_id)
                )
            ).first()
            if hold_row is None:
                raise HoldNotFoundError(hold_id)
            if datetime.now(UTC) >= _ensure_utc(hold_row.expires_at):
                raise HoldExpiredError(hold_id)

            delete_result = await conn.execute(
                delete(models.holds).where(models.holds.c.id == hold_id)
            )
            if delete_result.rowcount == 0:
                # CR-01: the hold was concurrently released/expired-and-
                # reaped/re-confirmed between our SELECT above and this
                # DELETE — do not materialize a Booking from the now-stale
                # hold_row snapshot (that would silently override a
                # concurrent release_hold and can exceed capacity).
                raise HoldNotFoundError(hold_id)
            booking_payload = payload if payload is not None else {}
            # Hold -> Booking transition: the hold row is deleted and a
            # booking row inserted with the SAME id, inside one transaction.
            # business_id comes from the resolved hold_business_index value
            # (not the column default) — cancel_booking later needs NO
            # business_id mechanism precisely because this row always
            # carries the real, resolved tenant.
            await conn.execute(
                insert(models.bookings).values(
                    id=hold_row.id,
                    business_id=business_id,
                    resource_id=hold_row.resource_id,
                    slot_start=hold_row.slot_start,
                    slot_end=hold_row.slot_end,
                    payload=booking_payload,
                    status=BookingStatus.CONFIRMED.value,
                )
            )
            booking = Booking(
                id=hold_row.id,
                resource_id=hold_row.resource_id,
                slot_start=_ensure_utc(hold_row.slot_start),
                slot_end=_ensure_utc(hold_row.slot_end),
                payload=booking_payload,
            )
            if idempotency_key is not None:
                assert fp is not None
                await self._write_idempotency_record(
                    conn,
                    business_id,
                    "confirm_hold",
                    idempotency_key,
                    fp,
                    "booking",
                    booking.id,
                )
            return booking

    async def release_hold(self, hold_id: str) -> None:
        # Idempotent no-op on an unknown id, matching memory.py — no
        # existence check, no error if 0 rows affected. No business_id
        # mechanism needed (D-A) — hold_id is already a globally-unique
        # bearer token, and this method has no idempotency-table write of
        # its own to scope.
        async with self._engine.begin() as conn:
            await conn.execute(delete(models.holds).where(models.holds.c.id == hold_id))

    async def cancel_booking(self, booking_id: str) -> None:
        # No business_id mechanism needed (D-A) — bookings rows are never
        # deleted (status-flagged instead), so business_id is always
        # directly readable from the still-present row by booking_id alone;
        # no hold_business_index-style index is required here.
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(models.bookings)
                .where(
                    models.bookings.c.id == booking_id,
                    models.bookings.c.status != BookingStatus.CANCELLED.value,
                )
                .values(status=BookingStatus.CANCELLED.value)
            )
            if result.rowcount == 0:
                # D-04: never a silent no-op, mirrors memory.py's rejection
                # of unknown-or-already-cancelled ids.
                raise BookingNotFoundError(booking_id)


__all__ = ["SQLStore"]
