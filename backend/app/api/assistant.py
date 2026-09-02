"""The assistant's endpoints — a streaming chat and a small status probe.

Admin-only while Brian watches what it costs (config: assistant_admin_only).
The widget asks /assistant/status first and stays hidden unless it gets a yes,
so nobody sees a button that will only refuse them.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import read_access
from app.config import get_settings
from app.models import Role, User

router = APIRouter(tags=["assistant"])


class Turn(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    messages: list[Turn]
    page: str | None = None


def _is_admin(user: User) -> bool:
    # read_access hands back the User row, not a dict — .get("role") would be
    # None for everyone and quietly lock out the admin it is meant to admit.
    return getattr(user, "role", None) == Role.admin


def _gate(user: User) -> None:
    s = get_settings()
    if not s.anthropic_api_key:
        raise HTTPException(status_code=503, detail="The assistant is not configured yet.")
    if s.assistant_admin_only and not _is_admin(user):
        raise HTTPException(status_code=403, detail="The assistant is limited to admins.")


@router.get("/assistant/status")
def assistant_status(user: User = Depends(read_access)):
    """Whether to show the launcher at all, and why not when it is off."""
    s = get_settings()
    allowed = bool(s.anthropic_api_key) and (
        not s.assistant_admin_only or _is_admin(user)
    )
    return {
        "enabled": allowed,
        "reason": (
            None if allowed
            else "not configured" if not s.anthropic_api_key
            else "admins only"
        ),
    }


@router.post("/assistant/ask")
def assistant_ask(body: AskRequest, user: User = Depends(read_access)):
    """Stream an answer as server-sent events."""
    _gate(user)
    from app.assistant import stream_reply

    history = [{"role": t.role, "content": t.content} for t in body.messages]
    if not history:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No message.")

    def events():
        try:
            for chunk in stream_reply(history, page=body.page):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as exc:  # noqa: BLE001 — the stream has already begun; tell the UI
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Without these a proxy will buffer the whole answer and defeat streaming.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
