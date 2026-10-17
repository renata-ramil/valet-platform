import base64
import hashlib
import hmac

from app.models import Role
from app.settings import settings
from app.sms import handle_inbound_sms, verify_twilio_signature

from tests.conftest import make_car, make_user


def _sign(url: str, params: dict[str, str]) -> str:
    data = url
    for key in sorted(params):
        data += key + params[key]
    return base64.b64encode(
        hmac.new(settings.twilio_auth_token.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()


def test_valid_signature_verifies():
    params = {"From": "+15551234567", "Body": "car"}
    url = "http://testserver/sms/inbound"
    signature = _sign(url, params)
    assert verify_twilio_signature(settings.twilio_auth_token, url, params, signature)


def test_tampered_body_fails_signature():
    params = {"From": "+15551234567", "Body": "car"}
    url = "http://testserver/sms/inbound"
    signature = _sign(url, params)
    tampered = dict(params, Body="7pm")
    assert not verify_twilio_signature(settings.twilio_auth_token, url, tampered, signature)


def test_unknown_sender_gets_generic_reply(db_session, building):
    reply = handle_inbound_sms(db_session, "+15550000000", "car")
    assert "isn't linked" in reply


def test_car_command_creates_a_queued_request(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "sms-resident@example.com")
    resident.phone_number = "+15551112222"
    db_session.add(resident)
    make_car(db_session, building.id, resident.id, "SMS001")
    db_session.commit()

    reply = handle_inbound_sms(db_session, "+15551112222", "car")

    assert "Your car will be ready" in reply
    from app.models import Request

    requests = db_session.query(Request).filter_by(owner_id=resident.id).all()
    assert len(requests) == 1
    assert requests[0].state == "queued"
    assert requests[0].source == "sms"


def test_time_command_books_a_scheduled_delivery(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "sms-resident2@example.com")
    resident.phone_number = "+15553334444"
    db_session.add(resident)
    make_car(db_session, building.id, resident.id, "SMS002")
    db_session.commit()

    reply = handle_inbound_sms(db_session, "+15553334444", "7pm")

    assert "Booked" in reply
    assert "7:00 PM" in reply


def test_unrecognized_text_gets_help_message(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "sms-resident3@example.com")
    resident.phone_number = "+15555556666"
    db_session.add(resident)
    make_car(db_session, building.id, resident.id, "SMS003")
    db_session.commit()

    reply = handle_inbound_sms(db_session, "+15555556666", "what is the weather")

    assert "Text" in reply


def test_endpoint_rejects_bad_signature(client, db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "sms-resident4@example.com")
    resident.phone_number = "+15557778888"
    db_session.add(resident)
    make_car(db_session, building.id, resident.id, "SMS004")
    db_session.commit()

    response = client.post(
        "/sms/inbound",
        data={"From": "+15557778888", "Body": "car"},
        headers={"X-Twilio-Signature": "not-a-real-signature"},
    )
    assert response.status_code == 403


def test_endpoint_accepts_valid_signature(client, db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "sms-resident5@example.com")
    resident.phone_number = "+15559990000"
    db_session.add(resident)
    make_car(db_session, building.id, resident.id, "SMS005")
    db_session.commit()

    params = {"From": "+15559990000", "Body": "car"}
    url = "http://testserver/sms/inbound"
    signature = _sign(url, params)

    response = client.post(
        "/sms/inbound", data=params, headers={"X-Twilio-Signature": signature}
    )
    assert response.status_code == 200
    assert "<Response>" in response.text
    assert "ready" in response.text.lower()
