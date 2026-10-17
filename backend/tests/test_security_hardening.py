from datetime import UTC, datetime, timedelta

from app.models import Role, UserSession
from app.security import SESSION_IDLE_TIMEOUT

from tests.conftest import make_user


def _login(client, email, password="password123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_login_is_rate_limited_per_ip(client, db_session, building):
    make_user(db_session, building.id, Role.resident, "resident@example.com")
    for _ in range(10):
        response = _login(client, "resident@example.com", password="wrong")
        assert response.status_code in (401, 429)
    limited = _login(client, "resident@example.com", password="wrong")
    assert limited.status_code == 429


def test_security_headers_present_on_every_response(client):
    response = client.get("/health")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]


def test_oversized_body_is_rejected(client, db_session, building):
    make_user(db_session, building.id, Role.resident, "resident@example.com")
    csrf = _login(client, "resident@example.com").json()["csrf_token"]
    huge_plate = "x" * 200_000
    response = client.post(
        "/cars",
        json={"make": "Honda", "model": "Civic", "color": "blue", "license_plate": huge_plate},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 413


def test_unhandled_error_returns_uniform_body_without_internals(client, db_session, building):
    make_user(db_session, building.id, Role.resident, "resident@example.com")
    csrf = _login(client, "resident@example.com").json()["csrf_token"]
    # Malformed JSON-shaped but wrong-typed field to probe for a leaked traceback
    response = client.post(
        "/requests",
        json={"car_id": {"not": "a string"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request"}


def test_idle_session_is_invalidated(client, db_session, building):
    user = make_user(db_session, building.id, Role.resident, "resident@example.com")
    csrf = _login(client, "resident@example.com").json()["csrf_token"]

    session = db_session.query(UserSession).filter_by(user_id=user.id).one()
    session.last_seen_at = datetime.now(UTC) - SESSION_IDLE_TIMEOUT - timedelta(minutes=1)
    db_session.add(session)
    db_session.commit()

    response = client.get("/requests", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 401
