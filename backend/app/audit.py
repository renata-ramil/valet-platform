import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent, Request, RequestEvent


def canonical_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(request_id: str, event_type: str, payload: str, prev_hash: str | None) -> str:
    body = canonical_json(
        {
            "request_id": request_id,
            "type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def append_event(
    db: Session,
    request: Request,
    event_type: str,
    payload: dict,
    actor_id: str | None,
    created_at: datetime | None = None,
) -> RequestEvent:
    # created_at defaults to now; a caller may backdate it (demo/history
    # seeding only, since the append-only trigger blocks fixing it up with
    # an UPDATE afterward) without affecting the hash, which never covers
    # created_at
    last_event = db.scalar(
        select(RequestEvent)
        .where(RequestEvent.request_id == request.id)
        .order_by(RequestEvent.sequence.desc())
        .limit(1)
    )
    prev_hash = last_event.hash if last_event else None
    sequence = (last_event.sequence + 1) if last_event else 1
    payload_json = canonical_json(payload)
    event_hash = compute_hash(request.id, event_type, payload_json, prev_hash)
    event = RequestEvent(
        request_id=request.id,
        building_id=request.building_id,
        actor_id=actor_id,
        type=event_type,
        payload=payload_json,
        sequence=sequence,
        prev_hash=prev_hash,
        hash=event_hash,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db.add(event)
    db.flush()
    return event


def compute_subject_hash(
    subject_type: str, subject_id: str, event_type: str, payload: str, prev_hash: str | None
) -> str:
    body = canonical_json(
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def append_audit_event(
    db: Session,
    building_id: str,
    subject_type: str,
    subject_id: str,
    event_type: str,
    payload: dict,
    actor_id: str | None,
    created_at: datetime | None = None,
) -> AuditEvent:
    """Appends a fleet or money event to the generic per-subject hash chain.

    Mirrors append_event above but is not tied to a Request, since a car,
    plan, invoice, payment or approval needs its own audit trail.
    """
    last_event = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.subject_type == subject_type, AuditEvent.subject_id == subject_id)
        .order_by(AuditEvent.sequence.desc())
        .limit(1)
    )
    prev_hash = last_event.hash if last_event else None
    sequence = (last_event.sequence + 1) if last_event else 1
    payload_json = canonical_json(payload)
    event_hash = compute_subject_hash(subject_type, subject_id, event_type, payload_json, prev_hash)
    event = AuditEvent(
        building_id=building_id,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_id=actor_id,
        type=event_type,
        payload=payload_json,
        sequence=sequence,
        prev_hash=prev_hash,
        hash=event_hash,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db.add(event)
    db.flush()
    return event


class BrokenChainError(Exception):
    def __init__(self, chain_id: str, event_id: str, position: int, reason: str):
        self.request_id = chain_id
        self.event_id = event_id
        self.position = position
        self.reason = reason
        super().__init__(
            f"Hash chain broken for {chain_id} at event {event_id} "
            f"(position {position}): {reason}"
        )


def verify_request_chain(events: Sequence[RequestEvent]) -> None:
    prev_hash = None
    expected_sequence = 1
    for position, event in enumerate(events):
        if event.sequence != expected_sequence:
            raise BrokenChainError(
                event.request_id,
                event.id,
                position,
                f"expected sequence {expected_sequence}, found {event.sequence} "
                "(an event was likely deleted)",
            )
        expected = compute_hash(event.request_id, event.type, event.payload, prev_hash)
        if event.prev_hash != prev_hash:
            raise BrokenChainError(
                event.request_id, event.id, position, "prev_hash does not match the prior event"
            )
        if expected != event.hash:
            raise BrokenChainError(
                event.request_id,
                event.id,
                position,
                "stored hash does not match its type, payload and prev_hash (tampered content)",
            )
        prev_hash = event.hash
        expected_sequence += 1


def verify_subject_chain(events: Sequence[AuditEvent]) -> None:
    prev_hash = None
    expected_sequence = 1
    for position, event in enumerate(events):
        if event.sequence != expected_sequence:
            raise BrokenChainError(
                f"{event.subject_type}:{event.subject_id}",
                event.id,
                position,
                f"expected sequence {expected_sequence}, found {event.sequence} "
                "(an event was likely deleted)",
            )
        expected = compute_subject_hash(
            event.subject_type, event.subject_id, event.type, event.payload, prev_hash
        )
        if event.prev_hash != prev_hash:
            raise BrokenChainError(
                f"{event.subject_type}:{event.subject_id}",
                event.id,
                position,
                "prev_hash does not match the prior event",
            )
        if expected != event.hash:
            raise BrokenChainError(
                f"{event.subject_type}:{event.subject_id}",
                event.id,
                position,
                "stored hash does not match its type, payload and prev_hash (tampered content)",
            )
        prev_hash = event.hash
        expected_sequence += 1


def verify_all(db: Session) -> list[BrokenChainError]:
    errors: list[BrokenChainError] = []
    request_ids = db.scalars(select(Request.id)).all()
    for request_id in request_ids:
        events = list(
            db.scalars(
                select(RequestEvent)
                .where(RequestEvent.request_id == request_id)
                .order_by(RequestEvent.sequence)
            )
        )
        try:
            verify_request_chain(events)
        except BrokenChainError as exc:
            errors.append(exc)

    subjects = db.execute(
        select(AuditEvent.subject_type, AuditEvent.subject_id).distinct()
    ).all()
    for subject_type, subject_id in subjects:
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.subject_type == subject_type, AuditEvent.subject_id == subject_id
                )
                .order_by(AuditEvent.sequence)
            )
        )
        try:
            verify_subject_chain(events)
        except BrokenChainError as exc:
            errors.append(exc)
    return errors


def install_append_only_trigger(bind, table_name: str = "request_events") -> None:
    dialect = bind.dialect.name
    func_name = f"forbid_{table_name}_mutation"
    trigger_name = f"{table_name}_no_mutate"
    if dialect == "postgresql":
        bind.execute(
            text(
                f"""
                CREATE OR REPLACE FUNCTION {func_name}()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION '{table_name} is append-only';
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        bind.execute(
            text(
                f"""
                DROP TRIGGER IF EXISTS {trigger_name} ON {table_name};
                CREATE TRIGGER {trigger_name}
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION {func_name}();
                """
            )
        )
    else:
        bind.execute(
            text(
                f"""
                CREATE TRIGGER IF NOT EXISTS {table_name}_no_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END;
                """
            )
        )
        bind.execute(
            text(
                f"""
                CREATE TRIGGER IF NOT EXISTS {table_name}_no_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END;
                """
            )
        )


def _main() -> int:
    from app.db import SessionLocal

    if len(sys.argv) < 2 or sys.argv[1] != "verify":
        print("Usage: python -m app.audit verify")
        return 2

    db = SessionLocal()
    try:
        errors = verify_all(db)
    finally:
        db.close()

    if not errors:
        print(
            "Audit chain OK: every request event chain and every fleet/money "
            "audit event chain is intact"
        )
        return 0

    for error in errors:
        print(f"BROKEN CHAIN: {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
