import uuid
from datetime import UTC, date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    resident = "resident"
    valet = "valet"
    manager = "manager"
    support = "support"


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    users: Mapped[list["User"]] = relationship(back_populates="building")
    cars: Mapped[list["Car"]] = relationship(back_populates="building")
    parking_spots: Mapped[list["ParkingSpot"]] = relationship(back_populates="building")
    invite_codes: Mapped[list["InviteCode"]] = relationship(back_populates="building")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(String(20))
    full_name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    calendar_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    building: Mapped[Building] = relationship(back_populates="users")
    cars: Mapped[list["Car"]] = relationship(back_populates="owner", foreign_keys="Car.owner_id")


class CarStatus(StrEnum):
    pending = "pending"
    active = "active"
    ended = "ended"


class Car(Base):
    __tablename__ = "cars"
    __table_args__ = (
        # Enforcing plate uniqueness only among non-ended cars in a building,
        # so a plate frees up once the old car row is ended
        Index(
            "ix_cars_plate_unique_active",
            "building_id",
            "license_plate",
            unique=True,
            sqlite_where=text("status != 'ended'"),
            postgresql_where=text("status != 'ended'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True, index=True)
    make: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(50))
    license_plate: Mapped[str] = mapped_column(String(20))
    status: Mapped[CarStatus] = mapped_column(String(20), default=CarStatus.active)
    started_on: Mapped[date] = mapped_column(Date, default=date.today)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    size_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    parking_spot_id: Mapped[str | None] = mapped_column(
        ForeignKey("parking_spots.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    building: Mapped[Building] = relationship(back_populates="cars")
    owner: Mapped[User] = relationship(back_populates="cars", foreign_keys=[owner_id])
    plan: Mapped["Plan | None"] = relationship()
    parking_spot: Mapped["ParkingSpot | None"] = relationship()


class ParkingSpot(Base):
    __tablename__ = "parking_spots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    lane: Mapped[int] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer)
    is_occupied: Mapped[bool] = mapped_column(Boolean, default=False)

    building: Mapped[Building] = relationship(back_populates="parking_spots")


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    role: Mapped[Role] = mapped_column(String(20))
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses_count: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    building: Mapped[Building] = relationship(back_populates="invite_codes")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Stamped by a successful TOTP check (login MFA or the /auth/totp/stepup
    # endpoint); money-moving staff actions require this to be recent
    totp_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LoginFailure(Base):
    __tablename__ = "login_failures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), index=True)
    ip_address: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TotpCredential(Base):
    __tablename__ = "totp_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    secret: Mapped[str] = mapped_column(String(64))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_codes_hash: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MfaChallenge(Base):
    __tablename__ = "mfa_challenges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RequestState(StrEnum):
    scheduled = "scheduled"
    queued = "queued"
    assigned = "assigned"
    retrieving = "retrieving"
    en_route = "en_route"
    delivered = "delivered"
    cancelled = "cancelled"
    failed = "failed"


class RequestSource(StrEnum):
    on_demand = "on_demand"
    scheduled = "scheduled"
    sms = "sms"


class ExceptionKind(StrEnum):
    skip = "skip"
    override = "override"


class TaskType(StrEnum):
    retrieve = "retrieve"
    deliver = "deliver"
    park = "park"
    restage = "restage"


def _weekdays_to_str(weekdays: list[int]) -> str:
    return ",".join(str(d) for d in sorted(set(weekdays)))


def _weekdays_from_str(raw: str) -> list[int]:
    return [int(d) for d in raw.split(",") if d != ""]


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    car_id: Mapped[str] = mapped_column(ForeignKey("cars.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    weekdays_raw: Mapped[str] = mapped_column("weekdays", String(20))
    ready_by_local_time: Mapped[time] = mapped_column(Time)
    active_from: Mapped[date] = mapped_column(Date)
    active_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    paused_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    exceptions: Mapped[list["ScheduleException"]] = relationship(
        back_populates="schedule", cascade="all, delete-orphan"
    )

    @property
    def weekdays(self) -> list[int]:
        return _weekdays_from_str(self.weekdays_raw)

    @weekdays.setter
    def weekdays(self, value: list[int]) -> None:
        self.weekdays_raw = _weekdays_to_str(value)


class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"
    __table_args__ = (UniqueConstraint("schedule_id", "local_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("schedules.id"), index=True)
    local_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[ExceptionKind] = mapped_column(String(20))
    override_local_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    schedule: Mapped[Schedule] = relationship(back_populates="exceptions")


class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (UniqueConstraint("schedule_id", "local_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    car_id: Mapped[str] = mapped_column(ForeignKey("cars.id"), index=True)
    source: Mapped[RequestSource] = mapped_column(String(20))
    ready_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[RequestState] = mapped_column(String(20), default=RequestState.queued)
    schedule_id: Mapped[str | None] = mapped_column(
        ForeignKey("schedules.id"), nullable=True, index=True
    )
    local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    events: Mapped[list["RequestEvent"]] = relationship(
        back_populates="request", order_by="RequestEvent.created_at"
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="request")


class RequestEvent(Base):
    __tablename__ = "request_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    request: Mapped[Request] = relationship(back_populates="events")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    type: Mapped[TaskType] = mapped_column(String(20))
    assigned_valet_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(20), default="pending")
    planned_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    request: Mapped[Request] = relationship(back_populates="tasks")


class ValetShift(Base):
    __tablename__ = "valet_shifts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    valet_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TicketStatus(StrEnum):
    open = "open"
    waiting = "waiting"
    resolved = "resolved"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("requests.id"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[TicketStatus] = mapped_column(String(20), default=TicketStatus.open)
    kind: Mapped[str] = mapped_column(String(20), default="general")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket", order_by="TicketMessage.created_at"
    )


class RescheduleProposal(Base):
    __tablename__ = "reschedule_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("schedules.id"), index=True)
    change_type: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    proposed_weekdays: Mapped[str | None] = mapped_column(String(20), nullable=True)
    proposed_ready_by_local_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    proposed_paused_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    ticket: Mapped[Ticket] = relationship(back_populates="messages")


class CarRequestAction(StrEnum):
    add = "add"
    remove = "remove"
    change = "change"


class CarRequestStatus(StrEnum):
    pending = "pending"
    applied = "applied"
    dismissed = "dismissed"


class CarRequest(Base):
    """A resident's structured add/remove/change request, backing a car_request ticket."""

    __tablename__ = "car_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), unique=True, index=True)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[CarRequestAction] = mapped_column(String(20))
    car_id: Mapped[str | None] = mapped_column(ForeignKey("cars.id"), nullable=True)
    plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CarRequestStatus] = mapped_column(String(20), default=CarRequestStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    size_class: Mapped[str] = mapped_column(String(30))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    prices: Mapped[list["PlanPrice"]] = relationship(
        back_populates="plan", order_by="PlanPrice.effective_month", cascade="all, delete-orphan"
    )


class PlanPrice(Base):
    __tablename__ = "plan_prices"
    __table_args__ = (UniqueConstraint("plan_id", "effective_month"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), index=True)
    # Always the first day of the billing month this price takes effect
    effective_month: Mapped[date] = mapped_column(Date)
    monthly_cents: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    plan: Mapped[Plan] = relationship(back_populates="prices")


class BillingAccount(Base):
    __tablename__ = "billing_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    autopay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Not a DB foreign key on purpose: payment_methods references billing_accounts,
    # and a mutual FK pair forces ALTER-based table creation that SQLite dislikes.
    # The app layer guarantees this id names a payment_methods row for this account.
    default_payment_method_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PaymentMethodKind(StrEnum):
    card = "card"
    bank = "bank"


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    billing_account_id: Mapped[str] = mapped_column(ForeignKey("billing_accounts.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_customer_id: Mapped[str] = mapped_column(String(120))
    provider_method_id: Mapped[str] = mapped_column(String(120))
    kind: Mapped[PaymentMethodKind] = mapped_column(String(20))
    brand: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last4: Mapped[str] = mapped_column(String(4))
    exp_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exp_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Only meaningful under FakeProvider: succeed, decline, requires_action, delayed_settle
    fake_behavior: Mapped[str] = mapped_column(String(20), default="succeed")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class InvoiceStatus(StrEnum):
    draft = "draft"
    open = "open"
    processing = "processing"
    paid = "paid"
    past_due = "past_due"
    void = "void"


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # One regular invoice per resident per period; adjustment invoices
        # (added lines after the regular invoice already issued) are exempt
        Index(
            "ix_invoices_one_per_period",
            "billing_account_id",
            "period_start",
            unique=True,
            sqlite_where=text("is_adjustment = 0"),
            postgresql_where=text("is_adjustment = false"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    billing_account_id: Mapped[str] = mapped_column(ForeignKey("billing_accounts.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[InvoiceStatus] = mapped_column(String(20), default=InvoiceStatus.open)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_adjustment: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    car_id: Mapped[str | None] = mapped_column(ForeignKey("cars.id"), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(Integer)
    days_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_in_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class PaymentStatus(StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"
    requires_action = "requires_action"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    billing_account_id: Mapped[str] = mapped_column(ForeignKey("billing_accounts.id"), index=True)
    method: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(20))
    provider_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[PaymentStatus] = mapped_column(String(20), default=PaymentStatus.pending)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_refund: Mapped[bool] = mapped_column(Boolean, default=False)
    refunded_payment_id: Mapped[str | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True
    )
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditBalance(Base):
    __tablename__ = "credit_balances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    billing_account_id: Mapped[str] = mapped_column(
        ForeignKey("billing_accounts.id"), unique=True, index=True
    )
    # Cached read of the ledger's credits account balance for this resident;
    # make reconcile recomputes it from ledger_entries and flags any drift
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LedgerAccount(StrEnum):
    receivable = "receivable"
    cash = "cash"
    revenue = "revenue"
    credits = "credits"
    refunds = "refunds"


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    # Groups the balanced set of rows making up one transaction
    transaction_id: Mapped[str] = mapped_column(String(36), index=True)
    account: Mapped[LedgerAccount] = mapped_column(String(20))
    debit_cents: Mapped[int] = mapped_column(Integer, default=0)
    credit_cents: Mapped[int] = mapped_column(Integer, default=0)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    billing_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_accounts.id"), nullable=True, index=True
    )
    memo: Mapped[str] = mapped_column(String(200))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(20))
    provider_event_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("user_id", "key", "method", "path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(200))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalKind(StrEnum):
    refund = "refund"
    credit = "credit"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    kind: Mapped[ApprovalKind] = mapped_column(String(20))
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    billing_account_id: Mapped[str] = mapped_column(ForeignKey("billing_accounts.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(300))
    original_payment_id: Mapped[str | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True
    )
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[ApprovalStatus] = mapped_column(String(20), default=ApprovalStatus.pending)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    """Generic hash-chained audit log for fleet and money actions.

    Mirrors RequestEvent's hash construction exactly (see app/audit.py) but
    chains per (subject_type, subject_id) instead of per request, since a
    plan, car, invoice, payment or approval is not a Request.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(30), index=True)
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
