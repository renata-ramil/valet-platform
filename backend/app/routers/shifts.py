from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf, require_role, scoped_query
from app.models import Role, User, ValetShift
from app.schemas import ShiftCreate, ShiftResponse

router = APIRouter(prefix="/shifts", tags=["shifts"], dependencies=[Depends(require_csrf)])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ShiftResponse)
def create_shift(
    payload: ShiftCreate,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> ValetShift:
    valet = db.get(User, payload.valet_id)
    if valet is None or valet.building_id != user.building_id or valet.role != Role.valet:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Valet not found")
    shift = ValetShift(
        building_id=user.building_id,
        valet_id=payload.valet_id,
        start_at=payload.start_at,
        end_at=payload.end_at,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.get("", response_model=list[ShiftResponse])
def list_shifts(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ValetShift]:
    query = scoped_query(ValetShift, user.building_id)
    if user.role not in (Role.manager,):
        query = query.where(ValetShift.valet_id == user.id)
    return list(db.scalars(query))


@router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift(
    shift_id: str,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> None:
    shift = db.scalar(scoped_query(ValetShift, user.building_id).where(ValetShift.id == shift_id))
    if shift is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shift not found")
    db.delete(shift)
    db.commit()
