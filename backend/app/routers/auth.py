from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_session, require_csrf
from app.models import InviteCode, TotpCredential, User, UserSession
from app.ratelimit import rate_limit
from app.schemas import LoginRequest, LoginResponse, MeResponse, RegisterRequest
from app.security import (
    SESSION_COOKIE_NAME,
    clear_login_failures,
    create_mfa_challenge,
    create_session,
    destroy_session,
    hash_password,
    is_locked_out,
    record_login_failure,
    verify_password,
)
from app.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_RATE_LIMIT = Depends(rate_limit("login", limit=10, window_seconds=60))
REGISTER_RATE_LIMIT = Depends(rate_limit("register", limit=10, window_seconds=60))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, session: UserSession) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.id,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=12 * 60 * 60,
    )


@router.post(
    "/register", status_code=status.HTTP_201_CREATED, dependencies=[REGISTER_RATE_LIMIT]
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> MeResponse:
    invite = db.scalar(select(InviteCode).where(InviteCode.code == payload.invite_code))
    if invite is None or invite.uses_count >= invite.max_uses:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid invite code")

    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")

    user = User(
        building_id=invite.building_id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=invite.role,
        full_name=payload.full_name,
        unit=invite.unit,
    )
    invite.uses_count += 1
    db.add(user)
    db.add(invite)
    db.commit()
    db.refresh(user)

    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        building_id=user.building_id,
        csrf_token="",
    )


def _login_response(user: User, session: UserSession) -> LoginResponse:
    return LoginResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        building_id=user.building_id,
        csrf_token=session.csrf_token,
    )


@router.post("/login", dependencies=[LOGIN_RATE_LIMIT])
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    ip = _client_ip(request)
    if is_locked_out(db, payload.email, ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts, try again later",
        )

    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(user.password_hash, payload.password):
        record_login_failure(db, payload.email, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    clear_login_failures(db, payload.email)

    credential = db.scalar(
        select(TotpCredential).where(
            TotpCredential.user_id == user.id, TotpCredential.confirmed.is_(True)
        )
    )
    if credential is not None:
        challenge = create_mfa_challenge(db, user.id)
        return LoginResponse(mfa_required=True, challenge_id=challenge.id)

    session = create_session(db, user.id, user.building_id)
    _set_session_cookie(response, session)
    return _login_response(user, session)


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(
    response: Response,
    session: UserSession = Depends(get_session),
    db: Session = Depends(get_db),
) -> dict:
    destroy_session(db, session.id)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "logged_out"}


@router.get("/me")
def me(
    user: User = Depends(get_current_user),
    session: UserSession = Depends(get_session),
) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        building_id=user.building_id,
        csrf_token=session.csrf_token,
    )
