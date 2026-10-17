import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.models import User
from app.support_assistant import run_confirm_action, run_support_turn
from app.support_tools import SupportContext

router = APIRouter(
    prefix="/support", tags=["support"], dependencies=[Depends(require_csrf)]
)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


class ConfirmRequest(BaseModel):
    proposal_id: str
    token: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat")
def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ctx = SupportContext(db=db, user=user)
    history = [{"role": t.role, "content": t.content} for t in payload.history]
    result = run_support_turn(ctx, history, payload.message)

    def stream():
        # Chunking the already-computed reply into word-sized SSE events.
        # The live-model path internally makes a single (non-streamed)
        # Anthropic call per turn, since the tool-calling loop needs the
        # full response to decide whether to call a tool; this still gives
        # the UI a progressive, token-by-token feel, documented in
        # docs/KNOWN-ISSUES.md rather than claimed as true model-token streaming.
        words = result.reply.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else f" {word}"
            yield _sse("token", {"text": chunk})
        yield _sse(
            "done",
            {
                "reply": result.reply,
                "proposal": result.proposal,
                "tool_calls": [
                    {"name": c.name, "error": c.error} for c in result.tool_calls
                ],
                "used_live_model": result.used_live_model,
                "refused": result.refused,
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/confirm")
def confirm(
    payload: ConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ctx = SupportContext(db=db, user=user)
    result = run_confirm_action(ctx, payload.proposal_id, payload.token)
    return {
        "reply": result.reply,
        "tool_calls": [{"name": c.name, "error": c.error} for c in result.tool_calls],
    }
