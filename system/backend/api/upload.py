"""Upload API — local multipart (legacy) + Cloudflare R2 presigned (Phase 4)."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.api.invite import require_beta_session, require_write_session
from backend.database import db
from backend.invite_db import BetaSession
from backend.models import ProjectResponse
from backend import r2 as r2_mod
from backend.saas_jobs import enqueue_job

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["③ 上传视频"],
)


def _require_project_access(project, session: BetaSession) -> None:
    if project.beta_account_id and project.beta_account_id != session.beta_account_id:
        raise HTTPException(status_code=404, detail="Project not found")


def _safe_filename(name: str) -> str:
    base = Path(name or "source.mp4").name
    cleaned = re.sub(r"[^\w.\-]+", "_", base).strip("._") or "source.mp4"
    return cleaned


def _guess_content_type(filename: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    lower = filename.lower()
    if lower.endswith(".mov"):
        return "video/quicktime"
    if lower.endswith(".webm"):
        return "video/webm"
    if lower.endswith(".mkv"):
        return "video/x-matroska"
    return "video/mp4"


# ---------------------------------------------------------------------------
# Request / response models (R2)
# ---------------------------------------------------------------------------


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., description="原始文件名，如 house.mov", examples=["house.mov"])
    project_id: str = Field(..., description="已创建的项目 ID", examples=["proj_abc123"])
    content_type: Optional[str] = Field(
        None,
        description="可选 MIME；不填则按扩展名猜测。PUT 时必须带相同 Content-Type。",
        examples=["video/mp4"],
    )


class UploadUrlResponse(BaseModel):
    upload_url: str = Field(..., description="浏览器 PUT 用的预签名 URL（约 1 小时有效）")
    url: str = Field(..., description="同 upload_url（兼容简写）")
    key: str = Field(..., description="R2 object key")
    bucket: str
    content_type: str
    expires_in: int = 3600
    project_id: str


class UploadCompleteRequest(BaseModel):
    project_id: str = Field(..., description="项目 ID")
    key: str = Field(..., description="上传时返回的 R2 key")
    create_job: bool = Field(
        True,
        description="上传完成后是否在 Supabase 创建 status=waiting 的 Job（给 Worker 拉）",
    )
    verify_object: bool = Field(
        True,
        description="是否对 R2 做 head_object 校验（确认文件已存在）",
    )


class UploadCompleteResponse(BaseModel):
    project_id: str
    status: str
    video_url: str
    key: str
    job_id: Optional[str] = None
    message: str = ""


# ---------------------------------------------------------------------------
# Legacy: multipart → local disk (kept for Studio / offline)
# ---------------------------------------------------------------------------


async def save_project_video(project_id: str, file: UploadFile) -> Path:
    """Persist upload under ``storage/projects/<id>/`` with a unique name."""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    filename = _safe_filename(file.filename or "source.mp4")
    dest = db.project_dir(project_id) / f"{project_id}_{filename}"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty upload")
    dest.write_bytes(content)

    project.video_path = str(dest.resolve())
    project.status = "video_uploaded"
    project.error = ""
    db.save_project(project)

    logger.info("Uploaded %s bytes → %s", len(content), dest)
    return dest


@router.post(
    "/upload",
    response_model=ProjectResponse,
    summary="本地直传视频（开发用）",
    description=(
        "表单上传到本机 `storage/projects/`。"
        "生产环境请用 **POST /api/upload-url** → 浏览器 PUT 到 R2 → **POST /api/upload-complete**。"
    ),
)
async def upload_video_local(
    project_id: str = Form(..., description="项目 ID，例如 proj_abc123"),
    file: UploadFile = File(..., description="带看视频文件"),
    session: BetaSession = Depends(require_beta_session),
) -> ProjectResponse:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)
    await save_project_video(project_id, file)
    return ProjectResponse(
        project_id=project_id,
        status="video_uploaded",
        message="Video uploaded (local disk)",
    )


# ---------------------------------------------------------------------------
# Phase 4: R2 presigned upload
# ---------------------------------------------------------------------------


@router.post(
    "/upload-url",
    response_model=UploadUrlResponse,
    summary="① 获取 R2 预签名上传地址",
    description=(
        "返回 Cloudflare R2 的 PUT URL。前端拿到后直接把视频 PUT 到 R2（不经 Backend 中转）。\n\n"
        "对象路径：`users/{beta_account_id}/projects/{project_id}/input/{uuid}_{filename}`\n\n"
        "PUT 时请带请求头：`Content-Type: <与返回的 content_type 相同>`。"
    ),
)
async def create_upload_url(
    body: UploadUrlRequest,
    session: BetaSession = Depends(require_beta_session),
) -> UploadUrlResponse:
    if not r2_mod.r2_configured():
        raise HTTPException(status_code=503, detail="R2 is not configured on the server")

    project = db.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)

    filename = _safe_filename(body.filename)
    content_type = _guess_content_type(filename, body.content_type)
    user_part = project.beta_account_id or project.user_id or "anonymous"
    key = (
        f"users/{user_part}/projects/{project.project_id}/input/"
        f"{uuid.uuid4().hex[:12]}_{filename}"
    )

    try:
        url = r2_mod.generate_upload_url(key, content_type=content_type, expires_in=3600)
    except r2_mod.R2NotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to create R2 upload URL")
        raise HTTPException(status_code=502, detail=f"R2 presign failed: {exc}") from exc

    return UploadUrlResponse(
        upload_url=url,
        url=url,
        key=key,
        bucket=r2_mod.R2_BUCKET,
        content_type=content_type,
        expires_in=3600,
        project_id=project.project_id,
    )


@router.post(
    "/upload-complete",
    response_model=UploadCompleteResponse,
    summary="② 上传完成 → 写入 Supabase + 创建 waiting Job",
    description=(
        "浏览器 PUT 到 R2 成功后调用。会：\n"
        "1. （可选）校验 R2 上文件存在\n"
        "2. 更新 projects.video_url / status=video_uploaded\n"
        "3. 创建 jobs.status=waiting（默认不立刻跑 AI，留给 Worker）"
    ),
)
async def upload_complete(
    body: UploadCompleteRequest,
    session: BetaSession = Depends(require_beta_session),
) -> UploadCompleteResponse:
    if not r2_mod.r2_configured():
        raise HTTPException(status_code=503, detail="R2 is not configured on the server")

    project = db.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)
    if f"/projects/{project.project_id}/" not in body.key and not body.key.startswith(
        f"users/"
    ):
        raise HTTPException(status_code=400, detail="Invalid object key for this project")

    if body.verify_object:
        try:
            if not r2_mod.object_exists(body.key):
                raise HTTPException(
                    status_code=400,
                    detail="Object not found in R2 — upload may have failed",
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("R2 head_object failed")
            raise HTTPException(status_code=502, detail=f"R2 verify failed: {exc}") from exc

    video_url = r2_mod.r2_public_uri(body.key)
    project.video_url = video_url
    # Keep video_path empty until Worker downloads for local AI pipeline
    project.status = "video_uploaded"
    project.error = ""
    db.save_project(project)

    job_id: Optional[str] = None
    if body.create_job:
        if project.status == "running":
            raise HTTPException(status_code=409, detail="A job is already running")
        job = enqueue_job(
            project,
            kind="create",
            stage="Queued",
            progress=0,
            status="waiting",
            input_url=video_url,
        )
        job_id = job.job_id
        logger.info(
            "upload-complete project=%s key=%s job=%s (waiting for worker)",
            project.project_id,
            body.key,
            job_id,
        )

    return UploadCompleteResponse(
        project_id=project.project_id,
        status=project.status,
        video_url=video_url,
        key=body.key,
        job_id=job_id,
        message=(
            "Upload recorded; job waiting for Worker"
            if job_id
            else "Upload recorded (no job created)"
        ),
    )
