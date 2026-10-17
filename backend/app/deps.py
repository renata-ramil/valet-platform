from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User, UserSession
from app.security import SESSION_COOKIE_NAME, get_valid_session, has_fresh_totp_stepup


def get_session(
    request: Request,
    db: Session = Depends(get_db),
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> UserSession:
    if session_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    session = get_valid_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    request.state.session = session
    return session


def require_csrf(
    request: Request,
    session: UserSession = Depends(get_session),
    x_csrf_token: str | None = Header(default=None),
) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if x_csrf_token is None or x_csrf_token != session.csrf_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token")


def get_current_user(
    session: UserSession = Depends(get_session),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


def require_role(*roles: Role):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this role")
        return user

    return _check


def scoped_query(model, building_id: str):
    # Adds the building filter so every caller inherits tenant isolation
    return select(model).where(model.building_id == building_id)


def require_money_stepup(
    user: User = Depends(require_role(Role.manager)),
    session: UserSession = Depends(get_session),
) -> User:
    # Staff money actions (record payment, credit, refund, void, approvals)
    # are manager-only and need a TOTP check within the last few minutes,
    # even if the session itself is older
    if not has_fresh_totp_stepup(session):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This action needs a fresh TOTP step-up (POST /auth/totp/stepup)",
        )
    return user
