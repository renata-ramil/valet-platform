from datetime import date, datetime, time

from pydantic import BaseModel, EmailStr, Field

from app.models import (
    ApprovalKind,
    ApprovalStatus,
    CarRequestAction,
    CarRequestStatus,
    CarStatus,
    ExceptionKind,
    InvoiceStatus,
    PaymentMethodKind,
    PaymentStatus,
    RequestSource,
    RequestState,
    Role,
    TicketStatus,
)


class RegisterRequest(BaseModel):
    invite_code: str
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: Role
    building_id: str
    csrf_token: str


class LoginResponse(BaseModel):
    # Flattened rather than nested so a non-MFA login's body is shaped exactly
    # like MeResponse, which is what existing callers already expect
    mfa_required: bool = False
    challenge_id: str | None = None
    id: str | None = None
    email: str | None = None
    full_name: str | None = None
    role: Role | None = None
    building_id: str | None = None
    csrf_token: str | None = None


class TotpEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str
    recovery_codes: list[str]


class TotpConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class TotpVerifyRequest(BaseModel):
    challenge_id: str
    code: str = Field(min_length=6, max_length=16)


class CarUpdate(BaseModel):
    # A resident may only rename their car; everything else is a manager action
    nickname: str | None = Field(default=None, max_length=60)


class CarResponse(BaseModel):
    id: str
    owner_id: str
    plan_id: str | None
    make: str
    model: str
    color: str
    license_plate: str
    status: CarStatus
    started_on: date
    ended_on: date | None
    size_class: str | None
    nickname: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InviteCodeCreate(BaseModel):
    role: Role
    max_uses: int = 1


class InviteCodeResponse(BaseModel):
    code: str
    role: Role
    max_uses: int

    model_config = {"from_attributes": True}


class RequestCreate(BaseModel):
    car_id: str
    ready_by: datetime | None = None


class RequestEventResponse(BaseModel):
    type: str
    payload: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RequestResponse(BaseModel):
    id: str
    owner_id: str
    car_id: str
    source: RequestSource
    ready_by: datetime
    state: RequestState
    resident_label: str
    schedule_id: str | None
    created_at: datetime
    events: list[RequestEventResponse] = []
    eta_ready_by: datetime | None = None
    eta_latest: datetime | None = None
    eta_calibrated: bool = False

    model_config = {"from_attributes": True}


class TransitionRequest(BaseModel):
    target_state: RequestState


class ScheduleCreate(BaseModel):
    car_id: str
    weekdays: list[int] = Field(min_length=1)
    ready_by_local_time: time
    active_from: date
    active_until: date | None = None


class ScheduleResponse(BaseModel):
    id: str
    car_id: str
    owner_id: str
    weekdays: list[int]
    ready_by_local_time: time
    active_from: date
    active_until: date | None
    paused_until: date | None

    model_config = {"from_attributes": True}


class ScheduleExceptionCreate(BaseModel):
    local_date: date
    kind: ExceptionKind
    override_local_time: time | None = None


class PauseUntilRequest(BaseModel):
    paused_until: date


class TaskResponse(BaseModel):
    id: str
    request_id: str
    type: str
    assigned_valet_id: str | None
    state: str
    planned_start_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ValetQueueItem(BaseModel):
    task: TaskResponse
    request: RequestResponse
    car: CarResponse
    lane: int | None
    depth: int | None
    minutes_to_deadline: float


class CarSearchResult(BaseModel):
    id: str
    license_plate: str
    make: str
    model: str
    color: str
    owner_name: str


class CarArrivedResponse(BaseModel):
    status: str
    task_id: str
    request_id: str


class ParkTaskCompleteResponse(BaseModel):
    status: str
    task_id: str
    lane: int | None
    depth: int | None


class ShiftCreate(BaseModel):
    valet_id: str
    start_at: datetime
    end_at: datetime


class ShiftResponse(BaseModel):
    id: str
    valet_id: str
    start_at: datetime
    end_at: datetime

    model_config = {"from_attributes": True}


class TicketCreate(BaseModel):
    subject: str
    request_id: str | None = None
    message: str


class TicketMessageCreate(BaseModel):
    body: str


class TicketMessageResponse(BaseModel):
    id: str
    author_id: str
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketResponse(BaseModel):
    id: str
    resident_id: str
    request_id: str | None
    subject: str
    status: TicketStatus
    created_at: datetime
    messages: list[TicketMessageResponse] = []

    model_config = {"from_attributes": True}


class TicketStatusUpdate(BaseModel):
    status: TicketStatus


class SuggestionResponse(BaseModel):
    weekdays: list[int]
    ready_by_local_time: str
    recurrence_probability: float
    observations: int


class ManagerDashboardResponse(BaseModel):
    counts_by_state: dict[str, int]
    valet_roster: list[dict]
    on_time_rate_today: float | None
    timeline: list[dict]


class WhatIfResponse(BaseModel):
    source: str
    seeds: int | None = None
    on_time_rate: float
    on_time_rate_ci: list[float] | None = None
    wait_p95_seconds: float
    wait_p95_seconds_ci: list[float] | None = None
    relocations_per_retrieval: float
    relocations_per_retrieval_ci: list[float] | None = None
    note: str | None = None


# Fleet (manager)


class ManagerCarCreate(BaseModel):
    resident_id: str
    make: str
    model: str
    color: str
    license_plate: str = Field(min_length=1, max_length=20)
    plan_id: str | None = None
    started_on: date | None = None
    size_class: str | None = None
    nickname: str | None = None


class ManagerCarUpdate(BaseModel):
    make: str | None = None
    model: str | None = None
    color: str | None = None
    license_plate: str | None = None
    plan_id: str | None = None
    size_class: str | None = None
    nickname: str | None = None


class CarEndRequest(BaseModel):
    ended_on: date | None = None


class ResidentSummary(BaseModel):
    id: str
    email: str
    full_name: str
    unit: str | None
    car_count: int

    model_config = {"from_attributes": True}


class ResidentDetailResponse(BaseModel):
    id: str
    email: str
    full_name: str
    unit: str | None
    cars: list[CarResponse]


class ImportCarsRequest(BaseModel):
    csv_text: str
    dry_run: bool = True


class ImportRowResultResponse(BaseModel):
    row_number: int
    status: str
    detail: str
    email: str | None
    license_plate: str | None


class ImportResultResponse(BaseModel):
    dry_run: bool
    ok_count: int
    error_count: int
    rows: list[ImportRowResultResponse]


class ResidentInviteRequest(BaseModel):
    unit: str
    max_uses: int = 1


class ResidentInviteResponse(BaseModel):
    code: str
    unit: str | None
    max_uses: int

    model_config = {"from_attributes": True}


class CarRequestCreate(BaseModel):
    action: CarRequestAction
    car_id: str | None = None
    plate: str | None = None
    make: str | None = None
    model: str | None = None
    color: str | None = None
    note: str | None = None


class CarRequestResponse(BaseModel):
    id: str
    ticket_id: str
    action: CarRequestAction
    status: CarRequestStatus
    car_id: str | None
    plate: str | None
    make: str | None
    model: str | None
    color: str | None
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# Plans


class PlanCreate(BaseModel):
    name: str
    size_class: str
    monthly_cents: int = Field(ge=0)


class PlanPriceChangeRequest(BaseModel):
    monthly_cents: int = Field(ge=0)
    effective_month: date


class PlanResponse(BaseModel):
    id: str
    name: str
    size_class: str
    archived: bool
    current_monthly_cents: int
    created_at: datetime


# Billing, resident-facing


class CarBillingSummary(BaseModel):
    car_id: str
    license_plate: str
    plan_name: str | None
    monthly_cents: int | None


class BillingSummaryResponse(BaseModel):
    amount_due_cents: int
    due_date: date | None
    autopay_enabled: bool
    paid_through: date | None
    cars: list[CarBillingSummary]


class InvoiceLineResponse(BaseModel):
    id: str
    car_id: str | None
    description: str
    amount_cents: int
    days_active: int | None
    days_in_month: int | None

    model_config = {"from_attributes": True}


class InvoiceResponse(BaseModel):
    id: str
    resident_id: str
    period_start: date
    period_end: date
    status: InvoiceStatus
    total_cents: int
    paid_cents: int
    due_at: datetime
    issued_at: datetime | None
    paid_at: datetime | None
    is_adjustment: bool
    lines: list[InvoiceLineResponse]


class PaymentMethodSetupRequest(BaseModel):
    kind: PaymentMethodKind = PaymentMethodKind.card
    fake_token: str | None = None


class PaymentMethodResponse(BaseModel):
    id: str
    kind: PaymentMethodKind
    brand: str | None
    last4: str
    exp_month: int | None
    exp_year: int | None
    is_active: bool
    pending: bool = False
    client_secret: str | None = None

    model_config = {"from_attributes": True}


class AutopayUpdateRequest(BaseModel):
    enabled: bool


class PayInvoiceRequest(BaseModel):
    payment_method_id: str | None = None


class PaymentResponse(BaseModel):
    id: str
    invoice_id: str
    method: str
    provider: str
    amount_cents: int
    status: PaymentStatus
    is_refund: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# Billing, manager-facing


class RecordPaymentRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    method: str = Field(pattern="^(cash|check|transfer)$")
    reference: str | None = None
    paid_on: date | None = None


class IssueCreditRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    reason: str = Field(min_length=1)


class RefundRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    reason: str = Field(min_length=1)
    payment_id: str


class VoidRequest(BaseModel):
    reason: str = Field(min_length=1)


class ApprovalDecisionRequest(BaseModel):
    approve: bool


class ApprovalResponse(BaseModel):
    id: str
    kind: ApprovalKind
    amount_cents: int
    reason: str
    status: ApprovalStatus
    requested_by: str
    approved_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
