"""Beta invite-code auth: create / verify / session check."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.invite_db import (
    COOKIE_NAME,
    generate_invite_code,
    describe_session_failure,
    get_valid_session,
    invite_db,
    verify_and_activate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/invite", tags=["⓪ Beta · 邀请码"])


class CreateInviteBody(BaseModel):
    code: Optional[str] = Field(
        None,
        description="可选自定义码；省略则自动生成 NESTO-XXXXXXXX",
    )


class CreateInviteResponse(BaseModel):
    code: str
    status: str = "active"


class VerifyInviteBody(BaseModel):
    code: str = Field(..., examples=["NESTO-A82KD91X"])
    device_id: str = Field(..., description="浏览器生成的设备指纹")
    used_by: Optional[str] = Field(None, description="可选邮箱 / 昵称")


class VerifyInviteResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    expires: Optional[str] = None
    beta_account_id: Optional[str] = None
    message: str = ""


class SessionInfoResponse(BaseModel):
    valid: bool
    invite_code: Optional[str] = None
    beta_account_id: Optional[str] = None
    expires: Optional[str] = None
    read_only: bool = False
    message: str = ""


def _admin_ok(x_admin_key: Optional[str]) -> bool:
    expected = (os.getenv("INVITE_ADMIN_KEY") or "").strip()
    if not expected:
        # Only allow open create in pure memory mode (local smoke tests).
        from backend.invite_db import invite_db

        return type(invite_db).__name__ == "_MemoryInviteStore"
    return bool(x_admin_key and x_admin_key.strip() == expected)


def _fmt(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.isoformat()


def extract_token(request: Request, authorization: Optional[str] = None) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie.strip()
    header = request.headers.get("x-nesto-session")
    if header:
        return header.strip()
    return None


async def require_beta_session(
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """FastAPI dependency — returns BetaSession or raises 401."""
    token = extract_token(request, authorization)
    failure = describe_session_failure(token or "")
    if failure:
        # Drop revoked sessions after telling the client why
        if failure.get("code") == "account_revoked" and token:
            invite_db.delete_session(token)
        raise HTTPException(status_code=401, detail=failure)
    sess = get_valid_session(token or "")
    if not sess or not sess.beta_account_id:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "session_missing",
                "message": "Invite expired or missing. Enter a valid invite code.",
            },
        )
    return sess


async def require_write_session(
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """Like require_beta_session but rejects admin View-as read-only tokens."""
    sess = await require_beta_session(request, authorization)
    if getattr(sess, "read_only", False):
        raise HTTPException(
            status_code=403,
            detail="Read-only view-as session — writes are disabled",
        )
    return sess


def _auth_failure_detail(token: Optional[str]) -> dict:
    return describe_session_failure(token or "") or {
        "code": "session_missing",
        "message": "Invite expired or missing. Enter a valid invite code.",
    }


@router.post(
    "/create",
    response_model=CreateInviteResponse,
    summary="管理员生成邀请码",
)
async def create_invite(
    body: CreateInviteBody = CreateInviteBody(),
    x_admin_key: Optional[str] = Header(default=None),
) -> CreateInviteResponse:
    if not _admin_ok(x_admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    try:
        inv = invite_db.create_code(body.code)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("Created invite code %s", inv.code)
    return CreateInviteResponse(code=inv.code, status=inv.status)


@router.get(
    "/list",
    summary="管理员列出邀请码（最近 50 条）",
)
async def list_invites(
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    if not _admin_ok(x_admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    items = invite_db.list_codes(50)
    return {
        "codes": [
            {
                "code": c.code,
                "status": c.status,
                "device_id": c.device_id,
                "activated_at": _fmt(c.activated_at),
                "expires_at": _fmt(c.expires_at),
                "created_at": _fmt(c.created_at),
            }
            for c in items
        ]
    }


@router.post(
    "/verify",
    response_model=VerifyInviteResponse,
    summary="用户验证邀请码并开启 3 小时 Session",
)
async def verify_invite(
    body: VerifyInviteBody,
    response: Response,
) -> VerifyInviteResponse:
    code = (body.code or "").strip()
    device_id = (body.device_id or "").strip()
    if not code or not device_id:
        return VerifyInviteResponse(success=False, message="Invalid code")

    try:
        sess, inv, account = verify_and_activate(
            code,
            device_id=device_id,
            used_by=body.used_by,
        )
    except LookupError:
        return VerifyInviteResponse(success=False, message="Invalid code")
    except PermissionError as exc:
        msg = str(exc)
        if "Already" in msg:
            return VerifyInviteResponse(success=False, message="Already used")
        if "Expired" in msg:
            return VerifyInviteResponse(success=False, message="Expired")
        if "Revoked" in msg:
            return VerifyInviteResponse(success=False, message="Revoked")
        return VerifyInviteResponse(success=False, message=msg)

    # Cookie for same-site / local; cross-origin Vercel also uses Bearer from JSON.
    max_age = max(1, int((sess.expires_at - sess.created_at).total_seconds()))
    response.set_cookie(
        key=COOKIE_NAME,
        value=sess.token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=max_age,
        path="/",
    )
    return VerifyInviteResponse(
        success=True,
        token=sess.token,
        expires=_fmt(sess.expires_at),
        beta_account_id=account.id,
        message="OK",
    )


@router.get(
    "/session",
    response_model=SessionInfoResponse,
    summary="检查当前 Session 是否仍有效",
)
async def session_info(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> SessionInfoResponse:
    token = extract_token(request, authorization)
    failure = describe_session_failure(token or "")
    if failure:
        if failure.get("code") == "account_revoked" and token:
            invite_db.delete_session(token)
        # 401 so browser clients (heartbeat / apiFetch) redirect to /invite
        raise HTTPException(status_code=401, detail=failure)
    sess = get_valid_session(token or "")
    if not sess:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "session_missing",
                "message": "Invite expired or missing. Enter a valid invite code.",
            },
        )
    return SessionInfoResponse(
        valid=True,
        invite_code=sess.invite_code,
        beta_account_id=sess.beta_account_id,
        expires=_fmt(sess.expires_at),
        read_only=bool(getattr(sess, "read_only", False)),
        message="OK",
    )


@router.post(
    "/logout",
    summary="结束当前 Session",
)
async def logout(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    token = extract_token(request, authorization)
    if token:
        from backend.invite_db import invite_db as store

        store.delete_session(token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


# Re-export for other modules
__all__ = [
    "router",
    "require_beta_session",
    "require_write_session",
    "extract_token",
    "COOKIE_NAME",
    "generate_invite_code",
]
