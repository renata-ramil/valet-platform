import time

from app.events import InProcessEventBus

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_in_process_bus_delivers_to_subscriber():
    bus = InProcessEventBus()
    subscription = bus.subscribe("user-1")
    bus.publish("user-1", {"type": "request_update", "state": "queued"})

    event_id, payload = subscription.get(timeout=1.0)
    assert event_id == 1
    assert payload["state"] == "queued"


def test_in_process_bus_replays_events_after_last_event_id():
    bus = InProcessEventBus()
    bus.publish("user-1", {"type": "request_update", "state": "queued"})
    bus.publish("user-1", {"type": "request_update", "state": "assigned"})

    subscription = bus.subscribe("user-1", last_event_id=1)
    event_id, payload = subscription.get(timeout=1.0)
    assert event_id == 2
    assert payload["state"] == "assigned"


def test_subscription_times_out_when_no_events():
    bus = InProcessEventBus()
    subscription = bus.subscribe("user-1")
    assert subscription.get(timeout=0.1) is None


def test_create_request_publishes_an_sse_event(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")

    from app.events import get_event_bus

    bus = get_event_bus()
    subscription = bus.subscribe(car.owner_id)

    start = time.monotonic()
    response = client.post(
        "/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 201

    item = subscription.get(timeout=2.0)
    latency = time.monotonic() - start
    assert item is not None
    event_id, payload = item
    assert payload["type"] == "request_update"
    assert payload["state"] == "queued"
    assert latency < 1.0
