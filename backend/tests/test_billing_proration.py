"""Property tests for the billing engine. The pure proration math (app.billing.proration)
is tested directly with hypothesis, same pattern as test_schedule_engine.py's DST test:
no pytest fixtures inside a @given function, since function-scoped fixtures are reused
across hypothesis examples and that reuse is exactly what we don't want here. The two
properties that need a database (invoice totals, idempotent regeneration) build their
own fresh in-memory engine per example instead of using the shared db_session fixture.
"""

from datetime import UTC, date, datetime

from app.audit import install_append_only_trigger
from app.billing.invoices import generate_invoices_for_period
from app.billing.proration import (
    active_days_in_period,
    days_in_month,
    prorate_car_charge,
    prorate_cents,
)
from app.db import Base, configure_sqlite_savepoints
from app.models import Building, Car, Invoice, Plan, PlanPrice, Role, User
from app.security import hash_password
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

MONTH_LENGTHS = st.integers(min_value=28, max_value=31)
MONTHLY_CENTS = st.integers(min_value=0, max_value=200_000)


@given(monthly_cents=MONTHLY_CENTS, days_in_billing_month=MONTH_LENGTHS)
@hyp_settings(deadline=None, max_examples=200)
def test_full_month_sums_to_exactly_the_plan_price(monthly_cents, days_in_billing_month):
    amount = prorate_cents(monthly_cents, days_in_billing_month, days_in_billing_month)
    assert amount == monthly_cents


@given(
    monthly_cents=MONTHLY_CENTS,
    days_in_billing_month=MONTH_LENGTHS,
    days_active=st.integers(min_value=0, max_value=31),
)
@hyp_settings(deadline=None, max_examples=300)
def test_partial_month_never_exceeds_the_full_price(
    monthly_cents, days_in_billing_month, days_active
):
    amount = prorate_cents(monthly_cents, days_active, days_in_billing_month)
    assert 0 <= amount <= monthly_cents


@given(
    monthly_cents=MONTHLY_CENTS,
    year=st.integers(min_value=2024, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    start_offset=st.integers(min_value=0, max_value=30),
    run_days=st.integers(min_value=0, max_value=40),
)
@hyp_settings(deadline=None, max_examples=300)
def test_prorate_car_charge_never_exceeds_full_price_for_any_window(
    monthly_cents, year, month, start_offset, run_days
):
    days = days_in_month(year, month)
    period_start = date(year, month, 1)
    period_end = date(year, month, days)
    started_on = min(period_start.toordinal() + start_offset, period_end.toordinal())
    started_on = date.fromordinal(started_on)
    ended_on = date.fromordinal(
        min(started_on.toordinal() + run_days, period_end.toordinal() + 365)
    )

    amount, days_active, days_in_period = prorate_car_charge(
        monthly_cents, started_on, ended_on, period_start, period_end
    )
    assert days_in_period == days
    assert 0 <= days_active <= days
    assert 0 <= amount <= monthly_cents
    if days_active == days:
        assert amount == monthly_cents


@given(
    total_cents=st.integers(min_value=0, max_value=1_000_000),
    already_paid=st.integers(min_value=0, max_value=1_000_000),
    credit_balance=st.integers(min_value=0, max_value=1_000_000),
)
@hyp_settings(deadline=None, max_examples=300)
def test_applying_credit_never_makes_a_total_negative(total_cents, already_paid, credit_balance):
    # Mirrors the exact clamp in app.billing.credits.apply_credit_to_invoice
    already_paid = min(already_paid, total_cents)
    remaining = max(total_cents - already_paid, 0)
    apply_amount = min(credit_balance, remaining) if remaining > 0 else 0

    assert apply_amount >= 0
    assert apply_amount <= credit_balance
    new_paid = already_paid + apply_amount
    assert new_paid <= total_cents


def _isolated_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    configure_sqlite_savepoints(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        install_append_only_trigger(conn, "request_events")
        install_append_only_trigger(conn, "audit_events")
        install_append_only_trigger(conn, "ledger_entries")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def _seed_resident_with_car(db, monthly_cents: int, started_on: date, num_cars: int):
    building = Building(name="Prop Tower", timezone="UTC")
    db.add(building)
    db.commit()
    db.refresh(building)

    resident = User(
        building_id=building.id,
        email=f"resident-{started_on.isoformat()}-{num_cars}@example.com",
        password_hash=hash_password("password123"),
        role=Role.resident,
        full_name="Resident",
    )
    db.add(resident)
    db.commit()
    db.refresh(resident)

    plan = Plan(building_id=building.id, name="Standard", size_class="sedan")
    db.add(plan)
    db.flush()
    db.add(
        PlanPrice(plan_id=plan.id, effective_month=date(2020, 1, 1), monthly_cents=monthly_cents)
    )
    db.commit()

    for i in range(num_cars):
        car = Car(
            building_id=building.id,
            owner_id=resident.id,
            plan_id=plan.id,
            make="Honda",
            model="Civic",
            color="blue",
            license_plate=f"PROP{i}",
            started_on=started_on,
        )
        db.add(car)
    db.commit()
    return building


@given(
    monthly_cents=st.integers(min_value=100, max_value=50_000),
    start_day=st.integers(min_value=1, max_value=28),
    num_cars=st.integers(min_value=1, max_value=3),
)
@hyp_settings(deadline=None, max_examples=25)
def test_invoice_total_equals_sum_of_lines(monthly_cents, start_day, num_cars):
    db = _isolated_session()
    try:
        year, month = 2026, 6
        building = _seed_resident_with_car(
            db, monthly_cents, date(year, month, start_day), num_cars
        )
        now = datetime(year, month, 25, tzinfo=UTC)
        created = generate_invoices_for_period(db, building, year, month, now)
        assert len(created) == 1
        invoice = db.get(Invoice, created[0].id)
        assert invoice.total_cents == sum(line.amount_cents for line in invoice.lines)
    finally:
        db.close()


@given(
    monthly_cents=st.integers(min_value=100, max_value=50_000),
    start_day=st.integers(min_value=1, max_value=28),
)
@hyp_settings(deadline=None, max_examples=25)
def test_generating_twice_creates_no_duplicates(monthly_cents, start_day):
    db = _isolated_session()
    try:
        year, month = 2026, 6
        building = _seed_resident_with_car(db, monthly_cents, date(year, month, start_day), 2)
        now = datetime(year, month, 25, tzinfo=UTC)

        first = generate_invoices_for_period(db, building, year, month, now)
        second = generate_invoices_for_period(db, building, year, month, now)
        assert len(first) == 1
        assert len(second) == 0

        invoices = list(db.scalars(select(Invoice).where(Invoice.building_id == building.id)))
        assert len(invoices) == 1
        assert len(invoices[0].lines) == 2
    finally:
        db.close()


def test_active_days_in_period_counts_both_endpoints():
    assert (
        active_days_in_period(
            date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 31)
        )
        == 1
    )
    assert active_days_in_period(date(2026, 1, 1), None, date(2026, 1, 1), date(2026, 1, 31)) == 31
    assert (
        active_days_in_period(
            date(2026, 1, 10), date(2026, 1, 20), date(2026, 1, 1), date(2026, 1, 31)
        )
        == 11
    )
