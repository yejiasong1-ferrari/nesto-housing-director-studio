"""Beta session presence heartbeat for Admin online status."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.invite import extract_token
from backend.invite_db import describe_session_failure, invite_db, touch_session_heartbeat

router = APIRouter(prefix="/api/session", tags=["Beta · Session"])


class HeartbeatBody(BaseModel):
    current_page: Optional[str] = Field(None, max_length=64)
    current_project: Optional[str] = Field(None, max_length=64)
    current_stage: Optional[str] = Field(None, max_length=64)


@router.post("/heartbeat", summary="Update session presence (every ~30s)")
async def heartbeat(
    request: Request,
    body: HeartbeatBody = HeartbeatBody(),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    token = extract_token(request, authorization)
    failure = describe_session_failure(token or "")
    if failure:
        if failure.get("code") == "account_revoked" and token:
            invite_db.delete_session(token)
        raise HTTPException(status_code=401, detail=failure)
    ua = request.headers.get("user-agent")
    client_ip = request.client.host if request.client else None
    sess = touch_session_heartbeat(
        token or "",
        current_page=body.current_page,
        current_project=body.current_project,
        current_stage=body.current_stage,
        user_agent=ua,
        client_ip=client_ip,
    )
    if not sess:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "session_missing",
                "message": "Invite expired or missing",
            },
        )
    return {
        "ok": True,
        "beta_account_id": sess.beta_account_id,
        "read_only": sess.read_only,
        "expires_at": sess.expires_at.isoformat() if sess.expires_at else None,
    }
