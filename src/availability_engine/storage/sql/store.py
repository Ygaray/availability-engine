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
from availability_engine.core.intervals import Interval
from availability_engine.errors import (
    BookingNotFoundError,
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
    IdempotencyConflictError,
)
from availability_engine.storage.memory import _fingerprint
from availability_engine.storage.sql import models
from availability_engine.storage.sql.locking import acquire_postgres_slot_lock


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
        self._engine = engine

    # -- Resource CRUD --------------------------------------------------

    async def save_resource(self, resource: Resource) -> None:
        definition = resource.model_dump(mode="json")
        async with self._engine.begin() as conn:
            existing_id = await conn.scalar(
                select(models.resources.c.id).where(
                    models.resources.c.id == resource.id
                )
            )
            if existing_id is None:
                await conn.execute(
                    insert(models.resources).values(
                        id=resource.id, definition=definition
                    )
                )
            else:
                await conn.execute(
                    update(models.resources)
                    .where(models.resources.c.id == resource.id)
                    .values(definition=definition)
                )

    async def get_resource(self, resource_id: str) -> Resource | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(models.resources.c.definition).where(
                        models.resources.c.id == resource_id
                    )
                )
            ).first()
        if row is None:
            return None
        return Resource.model_validate(row.definition)

    # -- Active-entries primitive (AVAIL-03) -----------------------------

    async def get_active_entries(
        self, resource_id: str, window: Interval
    ) -> list[Hold | Booking]:
        async with self._engine.connect() as conn:
            return await self._get_active_entries(conn, resource_id, window)

    async def _get_active_entries(
        self, conn: AsyncConnection, resource_id: str, window: Interval
    ) -> list[Hold | Booking]:
        # AVAIL-03/HOLD-05: the ONE shared, expiry-filtering active-entries
        # primitive — both the public Protocol method and place_hold's
        # capacity check call this, never a second, duplicate scan.
        now = datetime.now(UTC)
        entries: list[Hold | Booking] = []
        hold_rows = (
            await conn.execute(
                select(models.holds).where(
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
        self, conn: AsyncConnection, operation_type: str, key: str
    ) -> _IdempotencyRow | None:
        row = (
            await conn.execute(
                select(
                    models.idempotency.c.fingerprint,
                    models.idempotency.c.result_type,
                    models.idempotency.c.result_id,
                ).where(
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
                        operation_type=operation_type,
                        key=key,
                        fingerprint=fingerprint,
                        result_type=result_type,
                        result_id=result_id,
                    )
                )
        except IntegrityError:
            existing = await self._get_idempotency_record(conn, operation_type, key)
            if existing is None or existing.fingerprint != fingerprint:
                raise IdempotencyConflictError(operation_type, key) from None
            # Fingerprint matches — the racing writer's record already
            # captured this same logical call; this call's own write was
            # simply redundant, nothing further to do.

    # -- Hold / Booking lifecycle -----------------------------------------

    async def place_hold(
        self,
        resource_id: str,
        slot: Interval,
        capacity: int,
        ttl_seconds: int,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Hold:
        async with self._engine.begin() as conn:
            if conn.engine.dialect.name == "postgresql":
                await acquire_postgres_slot_lock(
                    conn, resource_id, slot.start.isoformat()
                )
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
                    conn, "place_hold", idempotency_key
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
            # supplied snapshot.
            resource_row = (
                await conn.execute(
                    select(models.resources.c.definition).where(
                        models.resources.c.id == resource_id
                    )
                )
            ).first()
            effective_capacity = (
                Resource.model_validate(resource_row.definition).capacity
                if resource_row is not None
                else capacity
            )

            active = await self._get_active_entries(conn, resource_id, slot)
            if len(active) >= effective_capacity:
                # Never cache an idempotency record on this failure path —
                # a retry with the same key, after capacity frees up, must
                # be free to succeed.
                raise CapacityExhaustedError(resource_id, slot)

            hold_id = str(uuid.uuid4())
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
            await conn.execute(
                insert(models.holds).values(
                    id=hold_id,
                    resource_id=resource_id,
                    slot_start=slot.start,
                    slot_end=slot.end,
                    expires_at=expires_at,
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
                    conn, "place_hold", idempotency_key, fp, "hold", hold_id
                )
            return hold

    async def confirm_hold(
        self,
        hold_id: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Booking:
        async with self._engine.begin() as conn:
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
                    conn, "confirm_hold", idempotency_key
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

            await conn.execute(delete(models.holds).where(models.holds.c.id == hold_id))
            booking_payload = payload if payload is not None else {}
            # Hold -> Booking transition: the hold row is deleted and a
            # booking row inserted with the SAME id, inside one transaction.
            await conn.execute(
                insert(models.bookings).values(
                    id=hold_row.id,
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
                    conn, "confirm_hold", idempotency_key, fp, "booking", booking.id
                )
            return booking

    async def release_hold(self, hold_id: str) -> None:
        # Idempotent no-op on an unknown id, matching memory.py — no
        # existence check, no error if 0 rows affected.
        async with self._engine.begin() as conn:
            await conn.execute(delete(models.holds).where(models.holds.c.id == hold_id))

    async def cancel_booking(self, booking_id: str) -> None:
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
