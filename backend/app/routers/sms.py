from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.ratelimit import rate_limit
from app.settings import settings
from app.sms import handle_inbound_sms, verify_twilio_signature

router = APIRouter(prefix="/sms", tags=["sms"])


def _twiml(message: str) -> Response:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{message}</Message></Response>"
    )
    return Response(content=body, media_type="application/xml")


@router.post(
    "/inbound", dependencies=[Depends(rate_limit("sms-inbound", limit=30, window_seconds=60))]
)
async def inbound(
    request: Request,
    From: str = Form(...),
    Body: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    form = await request.form()
    params = {key: str(value) for key, value in form.multi_items()}
    signature = request.headers.get("x-twilio-signature", "")
    url = str(request.url)

    if not verify_twilio_signature(settings.twilio_auth_token, url, params, signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")

    reply = handle_inbound_sms(db, From, Body)
    return _twiml(reply)
