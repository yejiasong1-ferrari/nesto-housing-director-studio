"""User API — create / look up users in Supabase (or memory)."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException

from backend.api.invite import require_beta_session
from backend.database import db
from backend.models import CreateUserBody, User, UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/users",
    tags=["② 创建项目"],
    dependencies=[Depends(require_beta_session)],
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post(
    "",
    response_model=UserResponse,
    summary="创建用户",
    description="用邮箱创建一个用户。已存在则直接返回（幂等）。",
)
async def create_user(body: CreateUserBody) -> UserResponse:
    email = (body.email or "").strip().lower()
    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Valid email required")

    existing = db.get_user_by_email(email)
    if existing:
        return UserResponse(user_id=existing.user_id, email=existing.email, status="exists")

    user = User(user_id=db.new_id("user_"), email=email)
    db.create_user(user)
    logger.info("Created user %s <%s>", user.user_id, email)
    return UserResponse(user_id=user.user_id, email=user.email, status="created")


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="查询用户",
)
async def get_user(user_id: str) -> UserResponse:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(user_id=user.user_id, email=user.email, status="ok")
