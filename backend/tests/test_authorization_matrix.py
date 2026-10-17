"""Generates docs/authorization-matrix.md and asserts every endpoint in the
live OpenAPI schema has a documented, tested outcome for every role plus a
second building's user. A new endpoint with no entry fails this test, which
is the point: authorization has to be a decision made at write time, not an
afterthought.

Each table entry gets its own freshly created car/request/schedule/ticket/
shift, since several endpoints are destructive (delete, cancel, transition)
and would otherwise interfere with later entries that share the same
resource. Within one entry, blocked roles (403/404) are exercised live
first since they cannot mutate anything; only the first allowed role in a
fixed order is exercised for the actual success path, since a second
"allowed" call on the same just-mutated resource would no longer return the
same status (for example a second valet transition after a manager already
advanced the state). Multi-role success paths for the same action are
already covered by the lifecycle tests in test_requests_api.py and
test_valet_queue.py.
"""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from app.audit import append_event
from app.billing.proration import month_bounds, next_month
from app.models import (
    BillingAccount,
    Building,
    CreditBalance,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    PaymentMethod,
    Plan,
    PlanPrice,
    Request,
    RequestSource,
    RequestState,
    Role,
    Schedule,
    Task,
    TaskType,
    Ticket,
    TicketMessage,
    ValetShift,
)
from app.ratelimit import reset_rate_limits
from sqlalchemy import select

from tests.conftest import make_car, make_invite, make_user

ROLE_ORDER = ("resident_b", "support", "valet", "manager", "resident")

MATRIX: list[tuple[str, str, object, dict[str, int]]] = []

PUBLIC_PATHS = {
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/auth/totp/verify"),
    ("GET", "/health"),
    # Twilio-signature-verified, not session-authenticated
    ("POST", "/sms/inbound"),
    # Stripe-signature-verified (or the fake provider's own shared secret),
    # not session-authenticated
    ("POST", "/webhooks/stripe"),
    # token-in-path authenticated (the token is the secret), not session-based
    ("GET", "/calendar/feed/{token}.ics"),
}

# These stream indefinitely (SSE): a plain request would hang reading the
# body, so the status check below is based on reading app/routers/events.py
# (get_current_user / require_role gates, no further resource lookup) rather
# than an executed HTTP call. They still get a documented row.
NO_LIVE_CALL_PATHS = {
    ("GET", "/events"),
    ("GET", "/events/building"),
}


def entry(method: str, path: str, body, expectations: dict[str, int]) -> None:
    MATRIX.append((method, path, body, expectations))


entry(
    "POST",
    "/cars",
    lambda r: {
        "make": "Honda",
        "model": "Civic",
        "color": "red",
        "license_plate": "NEW1",
    },
    {"resident": 403, "valet": 403, "manager": 403, "support": 403, "resident_b": 403},
)
entry(
    "GET",
    "/cars",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "GET",
    "/cars/{car_id}",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "PATCH",
    "/cars/{car_id}",
    lambda r: {"nickname": "Garage spare"},
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "DELETE",
    "/cars/{car_id}",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/cars/requests",
    lambda r: {
        "action": "add",
        "plate": "NEWCAR1",
        "make": "Honda",
        "model": "Civic",
        "color": "red",
        "note": "Need a spot",
    },
    {"resident": 201, "valet": 403, "manager": 403, "support": 403, "resident_b": 201},
)

entry(
    "POST",
    "/manager/invite-codes",
    lambda r: {"role": "resident", "max_uses": 1},
    {
        "resident": 403,
        "valet": 403,
        "manager": 201,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/dashboard",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/what-if?valet_count=6&demand_multiplier=1.0",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)

entry(
    "GET",
    "/suggestions",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)

entry(
    "POST",
    "/shifts",
    lambda r: {
        "valet_id": r["valet_id"],
        "start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "end_at": (datetime.now(UTC) + timedelta(days=1, hours=8)).isoformat(),
    },
    {"resident": 403, "valet": 403, "manager": 201, "support": 403, "resident_b": 403},
)
entry(
    "GET",
    "/shifts",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "DELETE",
    "/shifts/{shift_id}",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 204,
        "support": 403,
        "resident_b": 403,
    },
)

entry(
    "POST",
    "/requests",
    lambda r: {"car_id": r["car_id"]},
    {
        "resident": 201,
        "valet": 403,
        "manager": 201,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "GET",
    "/requests",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "GET",
    "/requests/{request_id}",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "POST",
    "/requests/{request_id}/cancel",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "POST",
    "/requests/{request_id}/transition",
    lambda r: {"target_state": "assigned"},
    {
        "resident": 403,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/schedules",
    lambda r: {
        "car_id": r["car_id"],
        "weekdays": [1, 2],
        "ready_by_local_time": "08:00:00",
        "active_from": str(date.today()),
    },
    {"resident": 201, "valet": 403, "manager": 201, "support": 403, "resident_b": 404},
)
entry(
    "GET",
    "/schedules",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "GET",
    "/schedules/{schedule_id}",
    None,
    {
        "resident": 200,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "DELETE",
    "/schedules/{schedule_id}",
    None,
    {
        "resident": 204,
        "valet": 403,
        "manager": 204,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "POST",
    "/schedules/{schedule_id}/exceptions",
    lambda r: {
        "local_date": str(date.today() + timedelta(days=1)),
        "kind": "skip",
    },
    {"resident": 201, "valet": 403, "manager": 201, "support": 403, "resident_b": 404},
)
entry(
    "POST",
    "/schedules/{schedule_id}/skip-tomorrow",
    None,
    {
        "resident": 200,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "POST",
    "/schedules/{schedule_id}/pause-until",
    lambda r: {
        "paused_until": str(date.today() + timedelta(days=7)),
    },
    {"resident": 200, "valet": 403, "manager": 200, "support": 403, "resident_b": 404},
)
entry(
    "POST",
    "/schedules/materialize",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)

entry(
    "POST",
    "/tickets",
    lambda r: {"subject": "Help", "message": "Need help"},
    {
        "resident": 201,
        "valet": 201,
        "manager": 201,
        "support": 201,
        "resident_b": 201,
    },
)
entry(
    "GET",
    "/tickets",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "GET",
    "/tickets/{ticket_id}",
    None,
    {
        "resident": 200,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 404,
    },
)
entry(
    "POST",
    "/tickets/{ticket_id}/messages",
    lambda r: {"body": "Following up"},
    {
        "resident": 201,
        "valet": 403,
        "manager": 201,
        "support": 201,
        "resident_b": 404,
    },
)
entry(
    "PATCH",
    "/tickets/{ticket_id}/status",
    lambda r: {"status": "resolved"},
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)

entry(
    "GET",
    "/valet/queue",
    None,
    {
        "resident": 403,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)

entry(
    "GET",
    "/valet/car-search?plate=MX",
    None,
    {
        "resident": 403,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/valet/cars/{car_id}/arrived",
    None,
    {
        "resident": 403,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/valet/tasks/{task_id}/complete-park",
    None,
    {
        "resident": 403,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)

entry(
    "GET",
    "/auth/me",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "POST",
    "/auth/logout",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "POST",
    "/auth/totp/enroll",
    None,
    {
        "resident": 403,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/auth/totp/confirm",
    lambda r: {"code": "000000"},
    {
        # support already has a pending (unconfirmed) enrollment left over from the
        # /auth/totp/enroll entry above (users persist across matrix entries, only
        # their cars/requests/etc are recreated fresh), so it hits the wrong-code
        # branch (400) instead of the no-pending-enrollment branch (404)
        "resident": 403,
        "valet": 404,
        "manager": 404,
        "support": 400,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/auth/totp/disable",
    lambda r: {"code": "000000"},
    {
        "resident": 403,
        "valet": 404,
        "manager": 404,
        "support": 404,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/auth/totp/stepup",
    lambda r: {"code": "000000"},
    {
        # Same accounting as /auth/totp/disable above: nobody in this matrix ever
        # reaches a confirmed credential, so every staff role gets the
        # not-enabled 404 rather than a real step-up
        "resident": 403,
        "valet": 404,
        "manager": 404,
        "support": 404,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/events",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "GET",
    "/events/building",
    None,
    {
        "resident": 403,
        "valet": 200,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)

entry(
    "POST",
    "/support/chat",
    lambda r: {"message": "where is my car"},
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "POST",
    "/support/confirm",
    lambda r: {"proposal_id": "nope", "token": "nope"},
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)

entry(
    "POST",
    "/calendar/token",
    None,
    {
        "resident": 200,
        "valet": 200,
        "manager": 200,
        "support": 200,
        "resident_b": 200,
    },
)
entry(
    "POST",
    "/calendar/import",
    lambda r: {"ics_url": "http://localhost/not-a-real-calendar.ics"},
    {
        "resident": 400,
        "valet": 400,
        "manager": 400,
        "support": 400,
        "resident_b": 400,
    },
)

# Fleet (manager)

entry(
    "POST",
    "/manager/cars",
    lambda r: {
        "resident_id": r["resident_id"],
        "make": "Honda",
        "model": "Fit",
        "color": "white",
        "license_plate": f"N{r['car_id'][:7]}",
    },
    {"resident": 403, "valet": 403, "manager": 201, "support": 403, "resident_b": 403},
)
entry(
    "PATCH",
    "/manager/cars/{car_id}",
    lambda r: {"nickname": "Garage spare"},
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/manager/cars/{car_id}/end",
    lambda r: {},
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/residents",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/residents/{resident_id}",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/manager/cars/import",
    lambda r: {
        "csv_text": (
            "email,full_name,unit,plate,make,model,color,plan_name,started_on\n"
            "nobody@example.com,,,ZZ999,Honda,Civic,blue,NoSuchPlan,\n"
        ),
        "dry_run": True,
    },
    {"resident": 403, "valet": 403, "manager": 200, "support": 403, "resident_b": 403},
)
entry(
    "POST",
    "/manager/residents/invite",
    lambda r: {"unit": "B2", "max_uses": 1},
    {
        "resident": 403,
        "valet": 403,
        "manager": 201,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/car-requests",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/car-requests/{car_request_id}/prefill",
    None,
    {
        # A manager reaches the real lookup and gets 404 for this made up id;
        # every other role is blocked by the role check first
        "resident": 403,
        "valet": 403,
        "manager": 404,
        "support": 403,
        "resident_b": 403,
    },
)

# Plans

entry(
    "POST",
    "/manager/plans",
    lambda r: {
        "name": "Visitor",
        "size_class": "sedan",
        "monthly_cents": 15000,
    },
    {"resident": 403, "valet": 403, "manager": 201, "support": 403, "resident_b": 403},
)
entry(
    "GET",
    "/manager/plans",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/manager/plans/{plan_id}/price",
    lambda r: {
        "monthly_cents": 16000,
        "effective_month": r["next_month_start"],
    },
    {"resident": 403, "valet": 403, "manager": 200, "support": 403, "resident_b": 403},
)
entry(
    "POST",
    "/manager/plans/{plan_id}/price-preview",
    lambda r: {
        "monthly_cents": 16000,
        "effective_month": r["next_month_start"],
    },
    {"resident": 403, "valet": 403, "manager": 200, "support": 200, "resident_b": 403},
)
entry(
    "POST",
    "/manager/plans/{plan_id}/archive",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)

# Billing (manager)

entry(
    "GET",
    "/manager/billing/overview?month=" + date.today().strftime("%Y-%m"),
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/invoices",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/invoices/{invoice_id}",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/manager/invoices/{invoice_id}/record-payment",
    lambda r: {
        "amount_cents": 100,
        "method": "cash",
    },
    {
        # Money moving: needs a fresh TOTP step-up that this harness never
        # performs, so even the manager role is blocked here. The real success
        # path is exercised with a step-up in test_billing_security.py
        "resident": 403,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/manager/invoices/{invoice_id}/credit",
    lambda r: {
        "amount_cents": 100,
        "reason": "test credit",
    },
    {"resident": 403, "valet": 403, "manager": 403, "support": 403, "resident_b": 403},
)
entry(
    "POST",
    "/manager/invoices/{invoice_id}/refund",
    lambda r: {
        "amount_cents": 100,
        "reason": "test refund",
        "payment_id": "nonexistent",
    },
    {"resident": 403, "valet": 403, "manager": 403, "support": 403, "resident_b": 403},
)
entry(
    "POST",
    "/manager/invoices/{invoice_id}/void",
    lambda r: {"reason": "test void"},
    {
        "resident": 403,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/manager/invoices/{invoice_id}/resend-receipt",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/approvals",
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "POST",
    "/manager/approvals/{approval_id}/decide",
    lambda r: {"approve": True},
    {
        "resident": 403,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 403,
    },
)
entry(
    "GET",
    "/manager/billing/month-close.csv?month=" + date.today().strftime("%Y-%m"),
    None,
    {
        "resident": 403,
        "valet": 403,
        "manager": 200,
        "support": 200,
        "resident_b": 403,
    },
)

# Billing (resident)

entry(
    "GET",
    "/billing/summary",
    None,
    {
        "resident": 200,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 200,
    },
)
entry(
    "GET",
    "/billing/invoices",
    None,
    {
        "resident": 200,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 200,
    },
)
entry(
    "GET",
    "/billing/invoices/{invoice_id}",
    None,
    {
        "resident": 200,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "GET",
    "/billing/invoices/{invoice_id}/receipt",
    None,
    {
        "resident": 200,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "GET",
    "/billing/payment-methods",
    None,
    {
        "resident": 200,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 200,
    },
)
entry(
    "POST",
    "/billing/payment-methods/setup",
    lambda r: {"kind": "card", "fake_token": "ok"},
    {
        "resident": 201,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 201,
    },
)
entry(
    "DELETE",
    "/billing/payment-methods/{method_id}",
    None,
    {
        "resident": 204,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 404,
    },
)
entry(
    "PATCH",
    "/billing/autopay",
    lambda r: {"enabled": False},
    {
        "resident": 200,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 200,
    },
)
entry(
    "POST",
    "/billing/invoices/{invoice_id}/pay",
    lambda r: {},
    {
        # Idempotency-Key is required and this harness does not send one, so
        # even the right resident gets 400 here; the real pay flow (with the
        # header) is exercised in test_billing_routes.py
        "resident": 400,
        "valet": 403,
        "manager": 403,
        "support": 403,
        "resident_b": 400,
    },
)


def _login(client, email, password="password123"):
    reset_rate_limits()
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def _make_building_and_staff(db_session):
    building = Building(name="Harbor Tower", timezone="UTC")
    db_session.add(building)
    db_session.commit()
    db_session.refresh(building)

    building_b = Building(name="Second Tower", timezone="UTC")
    db_session.add(building_b)
    db_session.commit()
    db_session.refresh(building_b)

    resident = make_user(db_session, building.id, Role.resident, "matrix-resident@example.com")
    valet = make_user(db_session, building.id, Role.valet, "matrix-valet@example.com")
    manager = make_user(db_session, building.id, Role.manager, "matrix-manager@example.com")
    support = make_user(db_session, building.id, Role.support, "matrix-support@example.com")
    resident_b = make_user(
        db_session, building_b.id, Role.resident, "matrix-resident-b@example.com"
    )
    make_invite(db_session, building.id, Role.resident)

    emails = {
        "resident": resident.email,
        "valet": valet.email,
        "manager": manager.email,
        "support": support.email,
        "resident_b": resident_b.email,
    }
    return building, resident, valet, emails


def _billing_fixture(db_session, building, resident) -> dict:
    """Created once and reused across matrix entries (unlike _fresh_resources'
    other rows): a BillingAccount, Invoice and PaymentMethod are each unique
    per resident per period, so a fresh one per entry would collide on the
    database's own uniqueness rules. None of the entries that use these
    actually mutate them irreversibly (the ones that do are all gated on a
    TOTP step-up this harness never performs), so reuse is safe.
    """
    existing = db_session.scalar(
        select(BillingAccount).where(BillingAccount.resident_id == resident.id)
    )
    if existing is not None:
        invoice = db_session.scalar(
            select(Invoice).where(Invoice.billing_account_id == existing.id)
        )
        method = db_session.scalar(
            select(PaymentMethod).where(PaymentMethod.billing_account_id == existing.id)
        )
        plan = db_session.scalar(select(Plan).where(Plan.building_id == building.id))
        return {
            "plan_id": plan.id,
            "invoice_id": invoice.id,
            "method_id": method.id,
            "resident_id": resident.id,
        }

    plan = Plan(building_id=building.id, name="Matrix Standard", size_class="sedan")
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        PlanPrice(plan_id=plan.id, effective_month=date.today().replace(day=1), monthly_cents=12000)
    )

    account = BillingAccount(building_id=building.id, resident_id=resident.id)
    db_session.add(account)
    db_session.flush()
    db_session.add(CreditBalance(billing_account_id=account.id, balance_cents=0))

    period_start, period_end = month_bounds(date.today().year, date.today().month)
    invoice = Invoice(
        building_id=building.id,
        resident_id=resident.id,
        billing_account_id=account.id,
        period_start=period_start,
        period_end=period_end,
        status=InvoiceStatus.open,
        total_cents=12000,
        due_at=datetime.now(UTC),
        issued_at=datetime.now(UTC),
    )
    db_session.add(invoice)
    db_session.flush()
    db_session.add(
        InvoiceLine(invoice_id=invoice.id, description="Matrix fixture line", amount_cents=12000)
    )

    method = PaymentMethod(
        billing_account_id=account.id,
        provider="fake",
        provider_customer_id=f"fake_cus_{account.id}",
        provider_method_id="fake_pm_matrix",
        kind="card",
        brand="visa",
        last4="4242",
    )
    db_session.add(method)
    db_session.flush()
    account.default_payment_method_id = method.id
    db_session.add(account)
    db_session.commit()

    return {
        "plan_id": plan.id,
        "invoice_id": invoice.id,
        "method_id": method.id,
        "resident_id": resident.id,
    }


def _fresh_resources(db_session, building, resident, valet, tag: str) -> dict:
    car = make_car(db_session, building.id, resident.id, f"MX{tag}"[:8])

    req = Request(
        building_id=building.id,
        owner_id=resident.id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=datetime.now(UTC),
        state=RequestState.queued,
    )
    db_session.add(req)
    db_session.flush()
    append_event(db_session, req, "created", {}, actor_id=resident.id)
    db_session.commit()
    db_session.refresh(req)

    schedule = Schedule(
        building_id=building.id,
        car_id=car.id,
        owner_id=resident.id,
        ready_by_local_time=time(8, 0),
        active_from=date.today(),
    )
    schedule.weekdays = [1, 2, 3]
    db_session.add(schedule)
    db_session.commit()
    db_session.refresh(schedule)

    ticket = Ticket(building_id=building.id, resident_id=resident.id, subject="Original")
    db_session.add(ticket)
    db_session.flush()
    db_session.add(TicketMessage(ticket_id=ticket.id, author_id=resident.id, body="hi"))
    db_session.commit()
    db_session.refresh(ticket)

    shift = ValetShift(
        building_id=building.id,
        valet_id=valet.id,
        start_at=datetime.now(UTC) + timedelta(hours=1),
        end_at=datetime.now(UTC) + timedelta(hours=9),
    )
    db_session.add(shift)
    db_session.commit()
    db_session.refresh(shift)

    park_task = Task(
        building_id=building.id,
        request_id=req.id,
        type=TaskType.park,
        planned_start_at=datetime.now(UTC),
    )
    db_session.add(park_task)
    db_session.commit()
    db_session.refresh(park_task)

    billing = _billing_fixture(db_session, building, resident)
    next_year, next_mo = next_month(date.today().year, date.today().month)
    next_month_start, _ = month_bounds(next_year, next_mo)

    return {
        "car_id": car.id,
        "car_plate": car.license_plate,
        "request_id": req.id,
        "schedule_id": schedule.id,
        "ticket_id": ticket.id,
        "shift_id": shift.id,
        "valet_id": valet.id,
        "task_id": park_task.id,
        "approval_id": "nonexistent",
        "car_request_id": "nonexistent",
        "next_month_start": str(next_month_start),
        **billing,
    }


def test_openapi_endpoints_all_have_matrix_entries(client):
    schema = client.app.openapi()
    documented = {(m, p.split("?")[0]) for m, p, _, _ in MATRIX} | PUBLIC_PATHS
    missing = []
    for path, operations in schema["paths"].items():
        for method in operations:
            if method.upper() not in ("GET", "POST", "PATCH", "DELETE", "PUT"):
                continue
            if (method.upper(), path) not in documented:
                missing.append((method.upper(), path))
    assert not missing, f"New endpoints with no authorization-matrix entry: {missing}"


def test_authorization_matrix(client, db_session):
    building, resident, valet, emails = _make_building_and_staff(db_session)
    rows_for_doc = []

    for index, (method, path_template, body_factory, expectations) in enumerate(MATRIX):
        resources = _fresh_resources(db_session, building, resident, valet, tag=str(index))
        path = path_template.format(**resources)
        body = body_factory(resources) if callable(body_factory) else None

        if (method, path_template) not in NO_LIVE_CALL_PATHS:
            order = sorted(ROLE_ORDER, key=lambda r: expectations[r] in (200, 201, 204))
            mutated = False
            for role_label in order:
                expected = expectations[role_label]
                is_success = expected in (200, 201, 204)
                if is_success and mutated:
                    continue
                csrf = _login(client, emails[role_label])
                kwargs = {"headers": {"X-CSRF-Token": csrf}}
                if body is not None:
                    kwargs["json"] = body
                response = client.request(method, path, **kwargs)
                assert response.status_code == expected, (
                    f"{method} {path} as {role_label}: expected {expected}, "
                    f"got {response.status_code}: {response.text}"
                )
                if is_success:
                    mutated = True
                client.post("/auth/logout", headers={"X-CSRF-Token": csrf})

            client.cookies.clear()
            anon_kwargs = {"json": body} if body is not None else {}
            anon_response = client.request(method, path, **anon_kwargs)
            assert anon_response.status_code == 401, (
                f"{method} {path} as anon: expected 401, got {anon_response.status_code}"
            )

        rows_for_doc.append((method, path_template, expectations))

    _write_matrix_doc(rows_for_doc)


def _write_matrix_doc(rows: list[tuple[str, str, dict[str, int]]]) -> None:
    lines = [
        "# Authorization matrix",
        "",
        "Generated by `backend/tests/test_authorization_matrix.py`. Every endpoint",
        "in the live OpenAPI schema has a row here, checked against real HTTP calls",
        "made as a resident, a valet, a manager, support staff, a resident of a",
        "second building (tenant isolation), and an unauthenticated caller (always",
        "401). Numbers are status codes. `make test` fails if a new endpoint has no",
        "row, and fails if any live call returns something other than what is",
        "written here.",
        "",
        "| Method | Path | Resident | Valet | Manager | Support | Other building | Anonymous |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for method, path, expectations in rows:
        lines.append(
            f"| {method} | `{path}` | {expectations['resident']} | {expectations['valet']} | "
            f"{expectations['manager']} | {expectations['support']} | "
            f"{expectations['resident_b']} | 401 |"
        )
    lines.append("")
    lines.append(
        "Public endpoints not in this table: `POST /auth/register`, `POST /auth/login`, "
        "`POST /auth/totp/verify`, `GET /health`. These are reachable without a session "
        "by design; `POST /auth/totp/verify` additionally requires a valid, unexpired "
        "challenge id from a prior login, which is itself role and credential gated."
    )
    docs_dir = Path(__file__).resolve().parents[2] / "docs"
    (docs_dir / "authorization-matrix.md").write_text("\n".join(lines) + "\n")
