"""Fills the database with 30 days of lived-in demo data: residents with
realistic routines (some with an explicit schedule, some with just enough
on-demand history for the habit detector to suggest one), valets with
shifts, a few open tickets, and a handful of in-flight requests today so
every screen has something to show. Writes a gitignored login sheet for
the demo. Run with `make demo` (or `python scripts/seed_demo.py` directly
with DATABASE_URL pointed at the database to fill)."""

import json
import random
import secrets
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.audit import append_event
from app.billing.charge import charge_invoice, record_manual_payment
from app.billing.credits import get_or_create_billing_account
from app.billing.invoices import generate_invoices_for_period
from app.db import Base, SessionLocal, engine
from app.fleet_service import create_car as fleet_create_car
from app.lifecycle import resident_label
from app.models import (
    ApprovalKind,
    ApprovalRequest,
    Building,
    Car,
    InviteCode,
    InvoiceStatus,
    ParkingSpot,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Plan,
    PlanPrice,
    Request,
    RequestSource,
    RequestState,
    Role,
    Schedule,
    Ticket,
    TicketMessage,
    User,
    ValetShift,
)
from app.payments.fake_provider import FakeProvider
from app.security import hash_password
from app.tasks import generate_tasks_for_request
from sqlalchemy import select

RNG_SEED = 20261009
RESIDENT_COUNT = 40
VALET_COUNT = 5
MANAGER_COUNT = 2
SUPPORT_COUNT = 1
LANES = 10
MAX_DEPTH = 6
HISTORY_DAYS = 30

PLAN_DEFS = [
    ("Compact", "compact", 11900),
    ("Standard", "standard", 15900),
    ("EV", "ev", 18900),
]


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


CAR_MAKES = ["Honda", "Toyota", "Tesla", "Ford", "BMW", "Subaru", "Kia", "Mazda"]
CAR_MODELS = ["Civic", "Camry", "Model 3", "F-150", "3 Series", "Outback", "Soul", "CX-5"]
COLORS = ["black", "white", "silver", "blue", "red", "gray"]
TICKET_SUBJECTS = [
    ("Key fob not working", "My key fob stopped working this morning, can someone check it?"),
    ("Scratch on bumper", "I noticed a small scratch on my rear bumper after pickup yesterday."),
    ("Billing question", "Is valet service included in my rent or billed separately?"),
    ("Late delivery", "My car was about 10 minutes late to the lobby this morning."),
]


def main() -> None:
    rng = random.Random(RNG_SEED)
    print("Creating tables")
    Base.metadata.create_all(engine)

    db = SessionLocal()
    passwords: dict[str, str] = {}

    def make_user(email: str, role: Role, full_name: str) -> User:
        password = secrets.token_urlsafe(9)
        passwords[email] = password
        user = User(
            building_id=building.id,
            email=email,
            password_hash=hash_password(password),
            role=role,
            full_name=full_name,
        )
        db.add(user)
        db.flush()
        return user

    try:
        print("Seeding Harbor Tower (demo)")
        building = Building(name="Harbor Tower", timezone="America/Los_Angeles")
        db.add(building)
        db.commit()
        db.refresh(building)

        print(f"Seeding garage layout: {LANES} lanes up to depth {MAX_DEPTH}")
        spots = []
        for lane in range(1, LANES + 1):
            for depth in range(1, MAX_DEPTH + 1):
                spot = ParkingSpot(building_id=building.id, lane=lane, depth=depth)
                db.add(spot)
                spots.append(spot)
        db.commit()
        for spot in spots:
            db.refresh(spot)

        print(f"Seeding {RESIDENT_COUNT} residents")
        residents = [
            make_user(f"resident{i}@harbortower.example.com", Role.resident, f"Resident {i}")
            for i in range(1, RESIDENT_COUNT + 1)
        ]
        db.commit()

        print(f"Seeding {VALET_COUNT} valets, {MANAGER_COUNT} managers, {SUPPORT_COUNT} support")
        valets = [
            make_user(f"valet{i}@harbortower.example.com", Role.valet, f"Valet {i}")
            for i in range(1, VALET_COUNT + 1)
        ]
        managers = [
            make_user(f"manager{i}@harbortower.example.com", Role.manager, f"Manager {i}")
            for i in range(1, MANAGER_COUNT + 1)
        ]
        make_user("support1@harbortower.example.com", Role.support, "Support 1")
        db.commit()

        print(f"Seeding {len(PLAN_DEFS)} plans")
        today_local = date.today()
        plan_start_year, plan_start_month = _shift_month(today_local.year, today_local.month, -7)
        plans = []
        for name, size_class, monthly_cents in PLAN_DEFS:
            plan = Plan(building_id=building.id, name=name, size_class=size_class)
            db.add(plan)
            db.flush()
            db.add(
                PlanPrice(
                    plan_id=plan.id,
                    effective_month=date(plan_start_year, plan_start_month, 1),
                    monthly_cents=monthly_cents,
                )
            )
            plans.append(plan)
        db.commit()

        print(
            "Seeding one car per resident with a plan, through the manager fleet "
            "service (app.fleet_service.create_car), parking most of them in the garage"
        )
        car_started_year, car_started_month = _shift_month(today_local.year, today_local.month, -6)
        car_started_on = date(car_started_year, car_started_month, 1)
        cars: dict[str, Car] = {}
        for i, resident in enumerate(residents):
            plan = plans[i % len(plans)]
            car = fleet_create_car(
                db,
                building,
                managers[0],
                resident.id,
                CAR_MAKES[i % len(CAR_MAKES)],
                CAR_MODELS[i % len(CAR_MODELS)],
                COLORS[i % len(COLORS)],
                f"{secrets.token_hex(3).upper()}",
                plan.id,
                car_started_on,
            )
            cars[resident.id] = car
            if (i + 1) % 10 == 0:
                print(f"  seeded cars for {i + 1}/{len(residents)} residents")

        print("Seeding valet shifts for the next 7 days")
        today_local = date.today()
        for day_offset in range(7):
            shift_date = today_local + timedelta(days=day_offset)
            for valet in valets:
                start = datetime.combine(shift_date, time(7, 0), tzinfo=UTC)
                db.add(
                    ValetShift(
                        building_id=building.id,
                        valet_id=valet.id,
                        start_at=start,
                        end_at=start + timedelta(hours=8),
                    )
                )
        db.commit()

        # Residents 0-9 get an explicit recurring schedule (weekday morning
        # routine); residents 10-14 get consistent on-demand history with no
        # schedule yet, so GET /suggestions detects a routine for them live;
        # the rest get occasional, irregular on-demand use
        routine_residents = residents[:10]
        suggestion_residents = residents[10:15]

        print(f"Seeding recurring schedules for {len(routine_residents)} residents")
        for i, resident in enumerate(routine_residents):
            hour = 7 + (i % 3)
            minute = rng.choice([0, 15, 30, 45])
            schedule = Schedule(
                building_id=building.id,
                car_id=cars[resident.id].id,
                owner_id=resident.id,
                ready_by_local_time=time(hour, minute),
                active_from=today_local - timedelta(days=HISTORY_DAYS),
            )
            schedule.weekdays = [0, 1, 2, 3, 4]
            db.add(schedule)
        db.commit()

        print(f"Generating {HISTORY_DAYS} days of request history")
        now = datetime.now(UTC)
        for day_offset in range(HISTORY_DAYS, 0, -1):
            day = now - timedelta(days=day_offset)
            is_weekday = day.weekday() < 5

            for resident in routine_residents + suggestion_residents:
                if is_weekday and rng.random() < 0.85:
                    hour = 7 + (residents.index(resident) % 3)
                    minute = rng.choice([0, 5, 10, 15, 30, 45])
                    ready_by = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    _seed_delivered_request(
                        db, building, resident, cars[resident.id], ready_by, rng
                    )

            for resident in residents[15:]:
                if rng.random() < 0.12:
                    hour = rng.randint(7, 20)
                    ready_by = day.replace(hour=hour, minute=rng.randint(0, 59), second=0)
                    _seed_delivered_request(
                        db, building, resident, cars[resident.id], ready_by, rng
                    )

            if day_offset % 5 == 0:
                print(f"  seeded day {HISTORY_DAYS - day_offset}/{HISTORY_DAYS}")
        db.commit()

        print("Seeding a few in-flight requests for today's demo")
        demo_flow_resident = routine_residents[0]
        _seed_active_request(
            db,
            building,
            demo_flow_resident,
            cars[demo_flow_resident.id],
            RequestState.queued,
            valets[0],
        )
        _seed_active_request(
            db,
            building,
            routine_residents[1],
            cars[routine_residents[1].id],
            RequestState.assigned,
            valets[1],
        )
        _seed_active_request(
            db,
            building,
            routine_residents[2],
            cars[routine_residents[2].id],
            RequestState.retrieving,
            valets[2],
        )
        _seed_active_request(
            db,
            building,
            routine_residents[3],
            cars[routine_residents[3].id],
            RequestState.en_route,
            valets[3],
        )
        db.commit()

        _seed_billing(db, building, managers, residents, rng)

        print("Seeding a few open tickets")
        for i, (subject, message) in enumerate(TICKET_SUBJECTS):
            resident = residents[i]
            ticket = Ticket(building_id=building.id, resident_id=resident.id, subject=subject)
            db.add(ticket)
            db.flush()
            db.add(TicketMessage(ticket_id=ticket.id, author_id=resident.id, body=message))
            db.commit()

        print("Creating a spare resident invite code")
        db.add(
            InviteCode(
                building_id=building.id, code="HARBOR-DEMO", role=Role.resident, max_uses=100
            )
        )
        db.commit()

        passwords_path = Path(__file__).resolve().parent / "seed_passwords.local.json"
        passwords_path.write_text(json.dumps(passwords, indent=2))

        login_sheet = _build_login_sheet(
            demo_flow_resident, routine_residents[5], valets[0], managers[0], passwords
        )
        login_sheet_path = Path(__file__).resolve().parent / "demo_login_sheet.local.md"
        login_sheet_path.write_text(login_sheet)

        print(
            f"Done: 1 building, {RESIDENT_COUNT} residents, {VALET_COUNT} valets, "
            f"{MANAGER_COUNT} managers, 1 support agent, {HISTORY_DAYS} days of history"
        )
        print(f"Wrote {login_sheet_path}")
    finally:
        db.close()


def _seed_delivered_request(db, building, resident, car, ready_by, rng) -> None:
    on_time = rng.random() < 0.88
    delay_seconds = 0 if on_time else rng.randint(60, 900)
    created_at = ready_by - timedelta(minutes=rng.randint(2, 20))
    request = Request(
        building_id=building.id,
        owner_id=resident.id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=ready_by,
        state=RequestState.delivered,
        created_at=created_at,
    )
    db.add(request)
    db.flush()

    # Spacing event timestamps across the actual historical window rather
    # than leaving them at append_event's insert-time default (today), so a
    # 30-day-old request's audit trail reads as 30 days old, not as
    # everything having happened "right now"
    delivered_at = ready_by + timedelta(seconds=delay_seconds)
    event_times = {
        "created": created_at,
        "assigned": created_at + timedelta(minutes=1),
        "retrieving": created_at + timedelta(minutes=2),
        "en_route": created_at + timedelta(minutes=3),
        "delivered": delivered_at,
    }
    for event_type, event_time in event_times.items():
        append_event(db, request, event_type, {}, actor_id=resident.id, created_at=event_time)
    db.add(request)


def _seed_active_request(db, building, resident, car, target_state, valet) -> None:
    now = datetime.now(UTC)
    request = Request(
        building_id=building.id,
        owner_id=resident.id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=now + timedelta(minutes=10),
        state=target_state,
        created_at=now - timedelta(minutes=5),
    )
    db.add(request)
    db.flush()
    states_reached = {
        RequestState.queued: ["created"],
        RequestState.assigned: ["created", "assigned"],
        RequestState.retrieving: ["created", "assigned", "retrieving"],
        RequestState.en_route: ["created", "assigned", "retrieving", "en_route"],
    }
    for event_type in states_reached[target_state]:
        append_event(db, request, event_type, {}, actor_id=resident.id)

    retrieve_task, deliver_task = generate_tasks_for_request(db, request)
    if target_state != RequestState.queued:
        retrieve_task.assigned_valet_id = valet.id
        retrieve_task.state = "in_progress" if target_state != RequestState.en_route else "done"
    if target_state == RequestState.en_route:
        deliver_task.assigned_valet_id = valet.id
        deliver_task.state = "in_progress"
    db.add(retrieve_task)
    db.add(deliver_task)

    print(
        f"  {resident.full_name}: {car.color} {car.make} {car.model} is "
        f"{resident_label(target_state)}"
    )


def _seed_billing(db, building, managers, residents, rng) -> None:
    """Three months of invoices with realistic outcomes: about 78% autopay,
    a few recovered declines, 6 residents past due on their latest invoice,
    and one refund proposal waiting for a second manager's approval.
    """
    today_local = date.today()
    billing_months = []
    for delta in (-3, -2, -1):
        billing_months.append(_shift_month(today_local.year, today_local.month, delta))

    print(f"Generating {len(billing_months)} months of invoices for {len(residents)} residents")
    now = datetime.now(UTC)
    provider = FakeProvider()

    shuffled = residents[:]
    rng.shuffle(shuffled)
    autopay_cutoff = int(len(residents) * 0.78)
    autopay_residents = {r.id for r in shuffled[:autopay_cutoff]}
    recovered_decline_residents = {r.id for r in shuffled[:3]}
    non_autopay_residents = shuffled[autopay_cutoff:]
    past_due_residents = non_autopay_residents[: min(6, len(non_autopay_residents))]
    past_due_ids = {r.id for r in past_due_residents}

    methods: dict[str, PaymentMethod] = {}
    for resident in residents:
        billing_account = get_or_create_billing_account(db, resident.id, building.id)
        if resident.id in autopay_residents:
            details = provider.setup_payment_method(
                billing_account.id, resident.email, "card", "ok"
            )
            method = PaymentMethod(
                billing_account_id=billing_account.id,
                provider="fake",
                provider_customer_id=details.provider_customer_id,
                provider_method_id=details.provider_method_id,
                kind=details.kind,
                brand=details.brand,
                last4=details.last4,
                fake_behavior=details.fake_behavior,
            )
            db.add(method)
            db.flush()
            billing_account.autopay_enabled = True
            billing_account.default_payment_method_id = method.id
            db.add(billing_account)
            methods[resident.id] = method
    db.commit()

    invoices_by_resident: dict[str, list] = {r.id: [] for r in residents}
    for month_index, (year, month) in enumerate(billing_months, start=1):
        created = generate_invoices_for_period(db, building, year, month, now)
        for invoice in created:
            invoices_by_resident.setdefault(invoice.resident_id, []).append(invoice)
        print(
            f"  month {month_index}/{len(billing_months)} ({year}-{month:02d}): "
            f"{len(created)} invoices issued"
        )

    attempt_counts: dict[str, int] = {r.id: 0 for r in residents}
    recovered = 0
    for resident in residents:
        resident_invoices = invoices_by_resident.get(resident.id, [])
        for position, invoice in enumerate(resident_invoices):
            is_last = position == len(resident_invoices) - 1
            if resident.id in autopay_residents:
                method = methods[resident.id]
                if resident.id in recovered_decline_residents and position == 0:
                    declining = PaymentMethod(
                        billing_account_id=method.billing_account_id,
                        provider="fake",
                        provider_customer_id=method.provider_customer_id,
                        provider_method_id=f"fake_pm_decline_{invoice.id}",
                        kind="card",
                        brand="visa",
                        last4="0002",
                        fake_behavior="decline",
                    )
                    db.add(declining)
                    db.flush()
                    attempt_counts[resident.id] += 1
                    charge_invoice(
                        db,
                        provider,
                        invoice,
                        declining,
                        f"{invoice.id}:{attempt_counts[resident.id]}",
                        attempt_counts[resident.id],
                        actor_id=None,
                        now=now,
                    )
                    attempt_counts[resident.id] += 1
                    charge_invoice(
                        db,
                        provider,
                        invoice,
                        method,
                        f"{invoice.id}:{attempt_counts[resident.id]}",
                        attempt_counts[resident.id],
                        actor_id=None,
                        now=now,
                    )
                    recovered += 1
                else:
                    attempt_counts[resident.id] += 1
                    charge_invoice(
                        db,
                        provider,
                        invoice,
                        method,
                        f"{invoice.id}:{attempt_counts[resident.id]}",
                        attempt_counts[resident.id],
                        actor_id=None,
                        now=now,
                    )
            elif resident.id in past_due_ids and is_last:
                invoice.status = InvoiceStatus.past_due
                db.add(invoice)
            else:
                record_manual_payment(
                    db,
                    invoice,
                    invoice.total_cents,
                    "check",
                    f"check-{rng.randint(1000, 9999)}",
                    managers[0].id,
                    now=now,
                )
        db.commit()

    print(
        f"  {len(autopay_residents)}/{len(residents)} residents on autopay, "
        f"{recovered} recovered declines, {len(past_due_ids)} past due on their latest invoice"
    )

    candidate = next(
        (
            r
            for r in residents
            if r.id in autopay_residents
            and r.id not in recovered_decline_residents
            and invoices_by_resident.get(r.id)
        ),
        None,
    )
    if candidate is not None:
        candidate_invoice = invoices_by_resident[candidate.id][-1]
        payment = db.scalar(
            select(Payment).where(
                Payment.invoice_id == candidate_invoice.id,
                Payment.status == PaymentStatus.succeeded,
            )
        )
        if payment is not None:
            billing_account = get_or_create_billing_account(db, candidate.id, building.id)
            approval = ApprovalRequest(
                building_id=building.id,
                kind=ApprovalKind.refund,
                invoice_id=candidate_invoice.id,
                billing_account_id=billing_account.id,
                amount_cents=max(payment.amount_cents, 25000),
                reason="Resident disputes a double charge; awaiting a second manager's review.",
                original_payment_id=payment.id,
                requested_by=managers[0].id,
            )
            db.add(approval)
            db.commit()
            print(f"  seeded one pending refund approval for {candidate.email}")


def _build_login_sheet(demo_resident, suggestion_resident, valet, manager, passwords) -> str:
    lines = [
        "# Demo login sheet (gitignored, do not commit or share)",
        "",
        "Generated by scripts/seed_demo.py. All passwords are random per run.",
        "",
        "## Walk through these in order (see docs/demo-script.md)",
        "",
        f"- Resident with an in-flight request: {demo_resident.email} / "
        f"{passwords[demo_resident.email]}",
        f"- Resident with enough history for a live habit suggestion: "
        f"{suggestion_resident.email} / {passwords[suggestion_resident.email]}",
        f"- Valet: {valet.email} / {passwords[valet.email]}",
        f"- Manager: {manager.email} / {passwords[manager.email]}",
        "",
        "## Everyone else",
        "",
        "See backend/scripts/seed_passwords.local.json for every seeded account's password.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
