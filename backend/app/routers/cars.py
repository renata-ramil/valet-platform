from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf, require_role, scoped_query
from app.fleet_service import create_car_request
from app.models import Building, Car, Role, User
from app.schemas import CarRequestCreate, CarRequestResponse, CarResponse, CarUpdate

router = APIRouter(prefix="/cars", tags=["cars"], dependencies=[Depends(require_csrf)])


def _get_owned_or_404(db: Session, user: User, car_id: str) -> Car:
    car = db.scalar(scoped_query(Car, user.building_id).where(Car.id == car_id))
    if car is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Car not found")
    if car.owner_id != user.id and user.role not in (Role.manager, Role.valet):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this car")
    return car


@router.post("", status_code=status.HTTP_201_CREATED)
def create_car_removed(user: User = Depends(get_current_user)) -> None:
    # Fleet ownership moved to managers (docs/BILLING.md decision 1): use
    # POST /manager/cars instead, which also attaches a resident and a plan
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "Only a manager can add a car, through POST /manager/cars"
    )


@router.post("/requests", status_code=status.HTTP_201_CREATED, response_model=CarRequestResponse)
def submit_car_request(
    payload: CarRequestCreate,
    user: User = Depends(require_role(Role.resident)),
    db: Session = Depends(get_db),
) -> CarRequestResponse:
    building = db.get(Building, user.building_id)
    car_request = create_car_request(
        db,
        building,
        user,
        payload.action,
        payload.car_id,
        payload.plate,
        payload.make,
        payload.model,
        payload.color,
        payload.note,
    )
    return CarRequestResponse.model_validate(car_request)


@router.get("", response_model=list[CarResponse])
def list_cars(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Car]:
    query = scoped_query(Car, user.building_id)
    if user.role not in (Role.manager, Role.valet):
        query = query.where(Car.owner_id == user.id)
    return list(db.scalars(query))


@router.get("/{car_id}", response_model=CarResponse)
def get_car(
    car_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Car:
    return _get_owned_or_404(db, user, car_id)


@router.patch("/{car_id}", response_model=CarResponse)
def update_car(
    car_id: str,
    payload: CarUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Car:
    # Residents may only rename their car; everything else about a car
    # (plate, make, model, color, plan, ending it) is a manager action
    car = _get_owned_or_404(db, user, car_id)
    if payload.nickname is not None:
        car.nickname = payload.nickname
    db.add(car)
    db.commit()
    db.refresh(car)
    return car


@router.delete("/{car_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_car_removed(user: User = Depends(get_current_user)) -> None:
    # Only a manager can end a car, through POST /manager/cars/{id}/end,
    # which prorates a credit instead of silently deleting billing history
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a manager can end a car, through POST /manager/cars/{id}/end",
    )
