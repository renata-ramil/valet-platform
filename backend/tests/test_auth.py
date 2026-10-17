from app.security import ACCOUNT_LOCKOUT_THRESHOLD

from tests.conftest import make_invite


def test_register_with_bad_invite_code_fails(client):
    response = client.post(
        "/auth/register",
        json={
            "invite_code": "not-a-real-code",
            "email": "resident@example.com",
            "password": "supersecret1",
            "full_name": "Res Ident",
        },
    )
    assert response.status_code == 400


def test_register_and_login(client, db_session, building):
    invite = make_invite(db_session, building.id)
    response = client.post(
        "/auth/register",
        json={
            "invite_code": invite.code,
            "email": "resident@example.com",
            "password": "supersecret1",
            "full_name": "Res Ident",
        },
    )
    assert response.status_code == 201

    login = client.post(
        "/auth/login", json={"email": "resident@example.com", "password": "supersecret1"}
    )
    assert login.status_code == 200
    assert "session_id" in login.cookies
    assert login.json()["csrf_token"]


def test_duplicate_email_registration_fails(client, db_session, building):
    invite = make_invite(db_session, building.id, max_uses=2)
    payload = {
        "invite_code": invite.code,
        "email": "dup@example.com",
        "password": "supersecret1",
        "full_name": "Dup User",
    }
    first = client.post("/auth/register", json=payload)
    assert first.status_code == 201
    second = client.post("/auth/register", json=payload)
    assert second.status_code == 400


def test_wrong_password_fails(client, db_session, building):
    invite = make_invite(db_session, building.id)
    client.post(
        "/auth/register",
        json={
            "invite_code": invite.code,
            "email": "resident@example.com",
            "password": "supersecret1",
            "full_name": "Res Ident",
        },
    )
    response = client.post(
        "/auth/login", json={"email": "resident@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_account_lockout_after_repeated_failures(client, db_session, building):
    invite = make_invite(db_session, building.id)
    client.post(
        "/auth/register",
        json={
            "invite_code": invite.code,
            "email": "resident@example.com",
            "password": "supersecret1",
            "full_name": "Res Ident",
        },
    )
    for _ in range(ACCOUNT_LOCKOUT_THRESHOLD):
        client.post(
            "/auth/login", json={"email": "resident@example.com", "password": "wrong-password"}
        )
    locked = client.post(
        "/auth/login", json={"email": "resident@example.com", "password": "supersecret1"}
    )
    assert locked.status_code == 429


def test_session_rotates_on_each_login(client, db_session, building):
    invite = make_invite(db_session, building.id)
    client.post(
        "/auth/register",
        json={
            "invite_code": invite.code,
            "email": "resident@example.com",
            "password": "supersecret1",
            "full_name": "Res Ident",
        },
    )
    first_login = client.post(
        "/auth/login", json={"email": "resident@example.com", "password": "supersecret1"}
    )
    first_session_id = first_login.cookies["session_id"]

    second_login = client.post(
        "/auth/login", json={"email": "resident@example.com", "password": "supersecret1"}
    )
    second_session_id = second_login.cookies["session_id"]

    assert first_session_id != second_session_id

    client.cookies.set("session_id", first_session_id)
    stale = client.get("/auth/me")
    assert stale.status_code == 401


def test_logout_without_csrf_header_is_rejected(client, db_session, building):
    invite = make_invite(db_session, building.id)
    client.post(
        "/auth/register",
        json={
            "invite_code": invite.code,
            "email": "resident@example.com",
            "password": "supersecret1",
            "full_name": "Res Ident",
        },
    )
    client.post(
        "/auth/login", json={"email": "resident@example.com", "password": "supersecret1"}
    )
    response = client.post("/auth/logout")
    assert response.status_code == 403


def test_logout_with_csrf_header_succeeds(client, db_session, building):
    invite = make_invite(db_session, building.id)
    client.post(
        "/auth/register",
        json={
            "invite_code": invite.code,
            "email": "resident@example.com",
            "password": "supersecret1",
            "full_name": "Res Ident",
        },
    )
    login = client.post(
        "/auth/login", json={"email": "resident@example.com", "password": "supersecret1"}
    )
    csrf = login.json()["csrf_token"]
    response = client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
