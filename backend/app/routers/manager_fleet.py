from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_csrf, require_role
from app.fleet_service import (
    create_car,
    end_car,
    import_cars_csv,
    invite_resident,
    list_residents,
    prefill_car_request,
    update_car,
)
from app.models import Building, Car, CarRequest, Plan, Role, User
from app.plan_service import archive_plan, create_plan, impact_preview, schedule_price_change
from app.schemas import (
    CarEndRequest,
    CarRequestResponse,
    CarResponse,
    ImportCarsRequest,
    ImportResultResponse,
    ImportRowResultResponse,
    ManagerCarCreate,
    ManagerCarUpdate,
    PlanCreate,
    PlanPriceChangeRequest,
    PlanResponse,
    ResidentDetailResponse,
    ResidentInviteRequest,
    ResidentInviteResponse,
    ResidentSummary,
)

router = APIRouter(prefix="/manager", tags=["manager-fleet"], dependencies=[Depends(require_csrf)])

READ_ROLES = (Role.manager, Role.support)


def _plan_price_cents_or_zero(db: Session, plan: Plan) -> int:
    from app.billing.invoices import plan_price_cents

    try:
        return plan_price_cents(db, plan.id, datetime.now(UTC).date())
    except ValueError:
        return 0


def _plan_to_response(db: Session, plan: Plan) -> PlanResponse:
    return PlanResponse(
        id=plan.id,
        name=plan.name,
        size_class=plan.size_class,
        archived=plan.archived,
        current_monthly_cents=_plan_price_cents_or_zero(db, plan),
        created_at=plan.created_at,
    )


def _car_or_404(db: Session, building: Building, car_id: str) -> Car:
    car = db.scalar(select(Car).where(Car.id == car_id, Car.building_id == building.id))
    if car is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Car not found")
    return car


@router.post("/cars", status_code=status.HTTP_201_CREATED, response_model=CarResponse)
def manager_create_car(
    payload: ManagerCarCreate,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> Car:
    building = db.get(Building, user.building_id)
    return create_car(
        db,
        building,
        user,
        payload.resident_id,
        payload.make,
        payload.model,
        payload.color,
        payload.license_plate,
        payload.plan_id,
        payload.started_on,
        payload.size_class,
        payload.nickname,
    )


@router.patch("/cars/{car_id}", response_model=CarResponse)
def manager_update_car(
    car_id: str,
    payload: ManagerCarUpdate,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> Car:
    building = db.get(Building, user.building_id)
    car = _car_or_404(db, building, car_id)
    return update_car(db, building, user, car, payload.model_dump(exclude_unset=True))


@router.post("/cars/{car_id}/end", response_model=CarResponse)
def manager_end_car(
    car_id: str,
    payload: CarEndRequest,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> Car:
    building = db.get(Building, user.building_id)
    car = _car_or_404(db, building, car_id)
    ended_on = payload.ended_on or datetime.now(UTC).date()
    return end_car(db, building, user, car, ended_on)


@router.get("/residents", response_model=list[ResidentSummary])
def manager_list_residents(
    search: str | None = Query(default=None),
    unit: str | None = Query(default=None),
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[ResidentSummary]:
    building = db.get(Building, user.building_id)
    residents = list_residents(db, building, search, unit)
    summaries = []
    for resident in residents:
        car_count = len(
            list(
                db.scalars(
                    select(Car).where(Car.owner_id == resident.id, Car.building_id == building.id)
                )
            )
        )
        summaries.append(
            ResidentSummary(
                id=resident.id,
                email=resident.email,
                full_name=resident.full_name,
                unit=resident.unit,
                car_count=car_count,
            )
        )
    return summaries


@router.get("/residents/{resident_id}", response_model=ResidentDetailResponse)
def manager_resident_detail(
    resident_id: str,
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> ResidentDetailResponse:
    resident = db.scalar(
        select(User).where(
            User.id == resident_id, User.building_id == user.building_id, User.role == Role.resident
        )
    )
    if resident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resident not found")
    cars = list(db.scalars(select(Car).where(Car.owner_id == resident.id)))
    return ResidentDetailResponse(
        id=resident.id,
        email=resident.email,
        full_name=resident.full_name,
        unit=resident.unit,
        cars=[CarResponse.model_validate(c) for c in cars],
    )


@router.post("/cars/import", response_model=ImportResultResponse)
def manager_import_cars(
    payload: ImportCarsRequest,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> ImportResultResponse:
    building = db.get(Building, user.building_id)
    result = import_cars_csv(db, building, user, payload.csv_text, payload.dry_run)
    return ImportResultResponse(
        dry_run=result.dry_run,
        ok_count=result.ok_count,
        error_count=result.error_count,
        rows=[
            ImportRowResultResponse(
                row_number=r.row_number,
                status=r.status,
                detail=r.detail,
                email=r.email,
                license_plate=r.license_plate,
            )
            for r in result.rows
        ],
    )


@router.post(
    "/residents/invite", status_code=status.HTTP_201_CREATED, response_model=ResidentInviteResponse
)
def manager_invite_resident(
    payload: ResidentInviteRequest,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> ResidentInviteResponse:
    building = db.get(Building, user.building_id)
    invite = invite_resident(db, building, user, payload.unit, payload.max_uses)
    return ResidentInviteResponse.model_validate(invite)


@router.get("/car-requests", response_model=list[CarRequestResponse])
def manager_list_car_requests(
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[CarRequestResponse]:
    requests = list(
        db.scalars(
            select(CarRequest)
            .where(CarRequest.building_id == user.building_id)
            .order_by(CarRequest.created_at.desc())
        )
    )
    return [CarRequestResponse.model_validate(r) for r in requests]


@router.get("/car-requests/{car_request_id}/prefill")
def manager_prefill_car_request(
    car_request_id: str,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> dict:
    car_request = db.scalar(
        select(CarRequest).where(
            CarRequest.id == car_request_id, CarRequest.building_id == user.building_id
        )
    )
    if car_request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Car request not found")
    return prefill_car_request(db, car_request)


# Plans


@router.post("/plans", status_code=status.HTTP_201_CREATED, response_model=PlanResponse)
def manager_create_plan(
    payload: PlanCreate,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> PlanResponse:
    building = db.get(Building, user.building_id)
    plan = create_plan(db, building, user, payload.name, payload.size_class, payload.monthly_cents)
    return _plan_to_response(db, plan)


@router.get("/plans", response_model=list[PlanResponse])
def manager_list_plans(
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[PlanResponse]:
    plans = list(db.scalars(select(Plan).where(Plan.building_id == user.building_id)))
    return [_plan_to_response(db, p) for p in plans]


def _plan_or_404(db: Session, building: Building, plan_id: str) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.id == plan_id, Plan.building_id == building.id))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return plan


@router.post("/plans/{plan_id}/price", response_model=PlanResponse)
def manager_schedule_price_change(
    plan_id: str,
    payload: PlanPriceChangeRequest,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> PlanResponse:
    building = db.get(Building, user.building_id)
    plan = _plan_or_404(db, building, plan_id)
    schedule_price_change(db, building, user, plan, payload.monthly_cents, payload.effective_month)
    return _plan_to_response(db, plan)


@router.post("/plans/{plan_id}/price-preview")
def manager_preview_price_change(
    plan_id: str,
    payload: PlanPriceChangeRequest,
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    building = db.get(Building, user.building_id)
    plan = _plan_or_404(db, building, plan_id)
    return impact_preview(db, building, plan, payload.monthly_cents, payload.effective_month)


@router.post("/plans/{plan_id}/archive", response_model=PlanResponse)
def manager_archive_plan(
    plan_id: str,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> PlanResponse:
    building = db.get(Building, user.building_id)
    plan = _plan_or_404(db, building, plan_id)
    archive_plan(db, building, user, plan)
    return _plan_to_response(db, plan)
