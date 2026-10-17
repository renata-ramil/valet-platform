import json
import secrets
from datetime import UTC, datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import LoginFailure, MfaChallenge, TotpCredential, User, UserSession

_hasher = PasswordHasher()

SESSION_COOKIE_NAME = "session_id"
SESSION_LIFETIME = timedelta(hours=12)
SESSION_IDLE_TIMEOUT = timedelta(minutes=30)

LOGIN_FAILURE_WINDOW = timedelta(minutes=15)
ACCOUNT_LOCKOUT_THRESHOLD = 5
IP_LOCKOUT_THRESHOLD = 20

MFA_CHALLENGE_LIFETIME = timedelta(minutes=5)
RECOVERY_CODE_COUNT = 8
TOTP_STEPUP_LIFETIME = timedelta(minutes=10)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def create_session(db: Session, user_id: str, building_id: str) -> UserSession:
    # Rotating sessions on login: drop any existing sessions for this user first
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    session = UserSession(
        id=secrets.token_urlsafe(32),
        user_id=user_id,
        building_id=building_id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=_now() + SESSION_LIFETIME,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def get_valid_session(db: Session, session_id: str) -> UserSession | None:
    session = db.get(UserSession, session_id)
    if session is None:
        return None
    if _aware(session.expires_at) < _now():
        db.delete(session)
        db.commit()
        return None
    if _aware(session.last_seen_at) + SESSION_IDLE_TIMEOUT < _now():
        db.delete(session)
        db.commit()
        return None
    session.last_seen_at = _now()
    db.add(session)
    db.commit()
    return session


def stamp_totp_stepup(db: Session, session: UserSession) -> UserSession:
    # Marks the session as freshly TOTP-verified; money-moving staff actions
    # check this is recent (see app.deps.require_money_stepup)
    session.totp_verified_at = _now()
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def has_fresh_totp_stepup(session: UserSession) -> bool:
    if session.totp_verified_at is None:
        return False
    return _aware(session.totp_verified_at) + TOTP_STEPUP_LIFETIME >= _now()


def rotate_session(db: Session, session: UserSession) -> UserSession:
    # Issuing a fresh session id and CSRF token after a privilege change
    # (for example enrolling in TOTP) so a token captured before the change
    # cannot outlive it
    destroy_session(db, session.id)
    return create_session(db, session.user_id, session.building_id)


def destroy_session(db: Session, session_id: str) -> None:
    db.execute(delete(UserSession).where(UserSession.id == session_id))
    db.commit()


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name="Valet platform")


def verify_totp_code(secret: str, code: str) -> bool:
    return pyotp.totp.TOTP(secret).verify(code, valid_window=1)


def generate_recovery_codes() -> list[str]:
    return [secrets.token_hex(5) for _ in range(RECOVERY_CODE_COUNT)]


def hash_recovery_codes(codes: list[str]) -> str:
    return json.dumps([hash_password(code) for code in codes])


def consume_recovery_code(db: Session, credential: TotpCredential, code: str) -> bool:
    hashes = json.loads(credential.recovery_codes_hash)
    for i, stored_hash in enumerate(hashes):
        if verify_password(stored_hash, code):
            del hashes[i]
            credential.recovery_codes_hash = json.dumps(hashes)
            db.add(credential)
            db.commit()
            return True
    return False


def create_mfa_challenge(db: Session, user_id: str) -> MfaChallenge:
    challenge = MfaChallenge(
        id=secrets.token_urlsafe(32),
        user_id=user_id,
        expires_at=_now() + MFA_CHALLENGE_LIFETIME,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge


def get_mfa_challenge_user(db: Session, challenge_id: str) -> User | None:
    # Does not delete the challenge: a wrong code should not burn the
    # resident's one chance to retry before it expires
    challenge = db.get(MfaChallenge, challenge_id)
    if challenge is None:
        return None
    if _aware(challenge.expires_at) < _now():
        db.delete(challenge)
        db.commit()
        return None
    return db.get(User, challenge.user_id)


def delete_mfa_challenge(db: Session, challenge_id: str) -> None:
    db.execute(delete(MfaChallenge).where(MfaChallenge.id == challenge_id))
    db.commit()


def record_login_failure(db: Session, email: str, ip_address: str) -> None:
    db.add(LoginFailure(email=email, ip_address=ip_address))
    db.commit()


def is_locked_out(db: Session, email: str, ip_address: str) -> bool:
    since = _now() - LOGIN_FAILURE_WINDOW
    account_count = len(
        db.scalars(
            select(LoginFailure.id).where(
                LoginFailure.email == email, LoginFailure.created_at >= since
            )
        ).all()
    )
    ip_count = len(
        db.scalars(
            select(LoginFailure.id).where(
                LoginFailure.ip_address == ip_address, LoginFailure.created_at >= since
            )
        ).all()
    )
    return account_count >= ACCOUNT_LOCKOUT_THRESHOLD or ip_count >= IP_LOCKOUT_THRESHOLD


def clear_login_failures(db: Session, email: str) -> None:
    db.execute(delete(LoginFailure).where(LoginFailure.email == email))
    db.commit()
