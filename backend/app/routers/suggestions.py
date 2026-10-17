import sys
from datetime import UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from fastapi import APIRouter, Depends
from ml.habits.model import detect_recurring_slots
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.models import Request, User
from app.schemas import SuggestionResponse

router = APIRouter(
    prefix="/suggestions", tags=["suggestions"], dependencies=[Depends(require_csrf)]
)


@router.get("", response_model=list[SuggestionResponse])
def get_suggestions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[SuggestionResponse]:
    requests = list(
        db.scalars(
            select(Request).where(Request.owner_id == user.id, Request.source == "on_demand")
        )
    )
    if not requests:
        return []

    created_times = [
        r.created_at if r.created_at.tzinfo is not None else r.created_at.replace(tzinfo=UTC)
        for r in requests
    ]
    earliest = min(created_times)

    rows = []
    for created in created_times:
        rows.append(
            {
                "weekday": created.weekday(),
                "time_minutes": created.hour * 60 + created.minute,
                "week_index": (created - earliest).days // 7,
            }
        )
    history = pd.DataFrame(rows)
    suggestions = detect_recurring_slots(history)

    return [
        SuggestionResponse(
            weekdays=s.weekdays,
            ready_by_local_time=f"{s.hour:02d}:{s.minute:02d}:00",
            recurrence_probability=s.recurrence_probability,
            observations=s.observations,
        )
        for s in suggestions
    ]
