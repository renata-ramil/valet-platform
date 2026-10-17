from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_session, require_csrf, require_role
from app.models import Role, TotpCredential, User, UserSession
from app.ratelimit import rate_limit
from app.schemas import MeResponse, TotpConfirmRequest, TotpEnrollResponse, TotpVerifyRequest
from app.security import (
    SESSION_COOKIE_NAME,
    consume_recovery_code,
    create_session,
    delete_mfa_challenge,
    generate_recovery_codes,
    generate_totp_secret,
    get_mfa_challenge_user,
    hash_recovery_codes,
    rotate_session,
    stamp_totp_stepup,
    totp_provisioning_uri,
    verify_totp_code,
)
from app.settings import settings

router = APIRouter(prefix="/auth/totp", tags=["auth"])

STAFF_ROLES = (Role.valet, Role.manager, Role.support)
VERIFY_RATE_LIMIT = Depends(rate_limit("totp-verify", limit=10, window_seconds=60))


def _set_session_cookie(response: Response, session: UserSession) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.id,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=12 * 60 * 60,
    )


@router.post("/enroll", response_model=TotpEnrollResponse, dependencies=[Depends(require_csrf)])
def enroll(
    user: User = Depends(require_role(*STAFF_ROLES)),
    db: Session = Depends(get_db),
) -> TotpEnrollResponse:
    db.execute(
        delete(TotpCredential).where(
            TotpCredential.user_id == user.id, TotpCredential.confirmed.is_(False)
        )
    )
    secret = generate_totp_secret()
    codes = generate_recovery_codes()
    credential = TotpCredential(
        user_id=user.id,
        secret=secret,
        confirmed=False,
        recovery_codes_hash=hash_recovery_codes(codes),
    )
    db.add(credential)
    db.commit()
    return TotpEnrollResponse(
        secret=secret,
        provisioning_uri=totp_provisioning_uri(secret, user.email),
        recovery_codes=codes,
    )


@router.post("/confirm", dependencies=[Depends(require_csrf)])
def confirm(
    payload: TotpConfirmRequest,
    response: Response,
    user: User = Depends(require_role(*STAFF_ROLES)),
    session: UserSession = Depends(get_session),
    db: Session = Depends(get_db),
) -> MeResponse:
    credential = db.scalar(
        select(TotpCredential).where(
            TotpCredential.user_id == user.id, TotpCredential.confirmed.is_(False)
        )
    )
    if credential is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending TOTP enrollment")
    if not verify_totp_code(credential.secret, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")

    credential.confirmed = True
    db.add(credential)
    db.commit()

    new_session = rotate_session(db, session)
    _set_session_cookie(response, new_session)
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        building_id=user.building_id,
        csrf_token=new_session.csrf_token,
    )


@router.post("/disable", dependencies=[Depends(require_csrf)])
def disable(
    payload: TotpConfirmRequest,
    response: Response,
    user: User = Depends(require_role(*STAFF_ROLES)),
    session: UserSession = Depends(get_session),
    db: Session = Depends(get_db),
) -> dict:
    credential = db.scalar(
        select(TotpCredential).where(
            TotpCredential.user_id == user.id, TotpCredential.confirmed.is_(True)
        )
    )
    if credential is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "TOTP is not enabled")
    if not verify_totp_code(credential.secret, payload.code) and not consume_recovery_code(
        db, credential, payload.code
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")

    db.delete(credential)
    db.commit()
    new_session = rotate_session(db, session)
    _set_session_cookie(response, new_session)
    return {"status": "disabled"}


@router.post("/verify", response_model=MeResponse, dependencies=[VERIFY_RATE_LIMIT])
def verify(
    payload: TotpVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MeResponse:
    user = get_mfa_challenge_user(db, payload.challenge_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Challenge expired or invalid")

    credential = db.scalar(
        select(TotpCredential).where(
            TotpCredential.user_id == user.id, TotpCredential.confirmed.is_(True)
        )
    )
    if credential is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "TOTP is not enabled for this account")

    if not verify_totp_code(credential.secret, payload.code) and not consume_recovery_code(
        db, credential, payload.code
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")

    delete_mfa_challenge(db, payload.challenge_id)
    session = create_session(db, user.id, user.building_id)
    # Logging in with TOTP already proves the step-up; no separate call needed
    # for the first 10 minutes of the session
    session = stamp_totp_stepup(db, session)
    _set_session_cookie(response, session)
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        building_id=user.building_id,
        csrf_token=session.csrf_token,
    )


@router.post("/stepup", response_model=MeResponse, dependencies=[Depends(require_csrf)])
def stepup(
    payload: TotpConfirmRequest,
    user: User = Depends(require_role(*STAFF_ROLES)),
    session: UserSession = Depends(get_session),
    db: Session = Depends(get_db),
) -> MeResponse:
    """Re-proves TOTP for an already logged in staff member before a money action."""
    credential = db.scalar(
        select(TotpCredential).where(
            TotpCredential.user_id == user.id, TotpCredential.confirmed.is_(True)
        )
    )
    if credential is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "TOTP is not enabled for this account")
    if not verify_totp_code(credential.secret, payload.code) and not consume_recovery_code(
        db, credential, payload.code
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")

    session = stamp_totp_stepup(db, session)
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        building_id=user.building_id,
        csrf_token=session.csrf_token,
    )
