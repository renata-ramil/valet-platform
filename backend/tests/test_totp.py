import pyotp
from app.models import Role

from tests.conftest import make_user


def _login(client, email, password="password123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_resident_cannot_enroll_in_totp(client, db_session, building):
    make_user(db_session, building.id, Role.resident, "resident@example.com")
    login = _login(client, "resident@example.com")
    csrf = login.json()["csrf_token"]

    response = client.post("/auth/totp/enroll", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403


def test_manager_enrolls_and_logs_in_with_totp(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "manager@example.com")
    login = _login(client, "manager@example.com")
    csrf = login.json()["csrf_token"]
    assert login.json()["mfa_required"] is False

    enroll = client.post("/auth/totp/enroll", headers={"X-CSRF-Token": csrf})
    assert enroll.status_code == 200
    body = enroll.json()
    secret = body["secret"]
    assert len(body["recovery_codes"]) == 8

    bad_confirm = client.post(
        "/auth/totp/confirm", json={"code": "000000"}, headers={"X-CSRF-Token": csrf}
    )
    assert bad_confirm.status_code == 400

    code = pyotp.TOTP(secret).now()
    confirm = client.post(
        "/auth/totp/confirm", json={"code": code}, headers={"X-CSRF-Token": csrf}
    )
    assert confirm.status_code == 200
    # Confirming rotates the session: the old csrf token is now invalid
    rotated_csrf = confirm.json()["csrf_token"]
    assert rotated_csrf != csrf

    stale = client.post("/auth/totp/disable", json={"code": code}, headers={"X-CSRF-Token": csrf})
    assert stale.status_code == 403

    client.post("/auth/logout", headers={"X-CSRF-Token": rotated_csrf})

    second_login = _login(client, "manager@example.com")
    assert second_login.status_code == 200
    second_body = second_login.json()
    assert second_body["mfa_required"] is True
    assert second_body["csrf_token"] is None
    challenge_id = second_body["challenge_id"]

    wrong_code = client.post(
        "/auth/totp/verify", json={"challenge_id": challenge_id, "code": "000000"}
    )
    assert wrong_code.status_code == 400

    verified = client.post(
        "/auth/totp/verify",
        json={"challenge_id": challenge_id, "code": pyotp.TOTP(secret).now()},
    )
    assert verified.status_code == 200
    assert verified.json()["role"] == "manager"


def test_recovery_code_logs_in_once(client, db_session, building):
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    login = _login(client, "valet@example.com")
    csrf = login.json()["csrf_token"]
    enroll = client.post("/auth/totp/enroll", headers={"X-CSRF-Token": csrf}).json()
    code = pyotp.TOTP(enroll["secret"]).now()
    client.post("/auth/totp/confirm", json={"code": code}, headers={"X-CSRF-Token": csrf})
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf})

    second_login = _login(client, "valet@example.com")
    challenge_id = second_login.json()["challenge_id"]
    recovery_code = enroll["recovery_codes"][0]

    verified = client.post(
        "/auth/totp/verify", json={"challenge_id": challenge_id, "code": recovery_code}
    )
    assert verified.status_code == 200

    client.post("/auth/logout", headers={"X-CSRF-Token": verified.json()["csrf_token"]})
    third_login = _login(client, "valet@example.com")
    reused = client.post(
        "/auth/totp/verify",
        json={"challenge_id": third_login.json()["challenge_id"], "code": recovery_code},
    )
    assert reused.status_code == 400


def test_mfa_challenge_cannot_be_reused(client, db_session, building):
    make_user(db_session, building.id, Role.support, "support@example.com")
    login = _login(client, "support@example.com")
    csrf = login.json()["csrf_token"]
    enroll = client.post("/auth/totp/enroll", headers={"X-CSRF-Token": csrf}).json()
    code = pyotp.TOTP(enroll["secret"]).now()
    client.post("/auth/totp/confirm", json={"code": code}, headers={"X-CSRF-Token": csrf})
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf})

    second_login = _login(client, "support@example.com")
    challenge_id = second_login.json()["challenge_id"]
    first = client.post(
        "/auth/totp/verify",
        json={"challenge_id": challenge_id, "code": pyotp.TOTP(enroll["secret"]).now()},
    )
    assert first.status_code == 200

    second = client.post(
        "/auth/totp/verify",
        json={"challenge_id": challenge_id, "code": pyotp.TOTP(enroll["secret"]).now()},
    )
    assert second.status_code == 400
