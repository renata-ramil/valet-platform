"""Idempotency-Key support for money-moving endpoints.

Every such endpoint requires the header and stores its response for 24
hours (settings.idempotency_record_hours); a repeated key on the same
route for the same user replays the stored response instead of acting
again, so a double click produces one charge.
"""

import json
from datetime import UTC, datetime, timedelta

from fastapi import Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IdempotencyRecord, User
from app.settings import settings


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if not idempotency_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key header is required")
    return idempotency_key


def find_cached_response(
    db: Session, user: User, key: str, method: str, path: str
) -> IdempotencyRecord | None:
    return db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.key == key,
            IdempotencyRecord.method == method,
            IdempotencyRecord.path == path,
        )
    )


def store_response(
    db: Session,
    building_id: str,
    user: User,
    key: str,
    method: str,
    path: str,
    response_status: int,
    response_body: dict,
) -> None:
    record = IdempotencyRecord(
        building_id=building_id,
        user_id=user.id,
        key=key,
        method=method,
        path=path,
        response_status=response_status,
        response_body=json.dumps(response_body, default=str),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.idempotency_record_hours),
    )
    db.add(record)
    db.flush()
