"""Nesto project API — create / inspect projects (service layer).

Pipeline execution lives in ``/api/jobs`` (calls ``generate_video``).
``POST /{id}/produce`` remains as a convenience that enqueues a job.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.api.invite import require_beta_session, require_write_session
from backend.api.jobs import _enqueue_generate, _should_run_job_in_api, start_job_task
from backend.api.upload import save_project_video
from backend.database import db
from backend.saas_jobs import mark_job_cancelled
from backend.invite_db import BetaSession
from backend.models import CreateProjectBody, Project, ProjectResponse, User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/projects",
    tags=["② 创建项目"],
)


def _normalize_language(language: str) -> str:
    lang = (language or "zh").strip().lower()
    if lang in ("en", "english"):
        return "en"
    if lang in ("zh", "chinese", "中文", "zh-cn", "zh_cn"):
        return "zh"
    raise HTTPException(status_code=400, detail="language must be 'en' or 'zh'")


def _resolve_user_id(user_id: Optional[str], email: Optional[str]) -> Optional[str]:
    if user_id:
        if not db.get_user(user_id):
            raise HTTPException(status_code=404, detail="User not found")
        return user_id
    if not email:
        return None
    email_norm = email.strip().lower()
    existing = db.get_user_by_email(email_norm)
    if existing:
        return existing.user_id
    user = User(user_id=db.new_id("user_"), email=email_norm)
    db.create_user(user)
    return user.user_id


def _require_project_access(project: Project, session: BetaSession) -> None:
    """Hide existence of other accounts' projects (404)."""
    owner = project.beta_account_id
    if owner and owner != session.beta_account_id:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post(
    "",
    response_model=ProjectResponse,
    summary="① 创建项目",
    description=(
        "填写导演意图 `brief`、旁白语言 `language`。\n\n"
        "项目绑定当前 Beta Session 的 `beta_account_id`（邀请码身份）。\n\n"
        "成功后记下 `project_id`，下一步去上传视频。"
    ),
)
async def create_project(
    body: CreateProjectBody,
    session: BetaSession = Depends(require_write_session),
) -> ProjectResponse:
    brief = (body.brief or body.prompt or "").strip()
    language = _normalize_language(body.language)
    project_id = db.new_id("proj_")
    # Optional legacy users row only — never put beta_account_id into user_id
    # (projects.user_id has FK → users.id).
    user_id = _resolve_user_id(body.user_id, body.email)
    title = (body.title or "Untitled").strip() or "Untitled"
    account_id = session.beta_account_id

    project = Project(
        project_id=project_id,
        user_id=user_id,
        beta_account_id=account_id,
        title=title,
        brief=brief,
        language=language,
        status="created",
        property_metadata=body.property_metadata or {},
    )
    db.create_project(project)
    db.project_dir(project_id)

    logger.info(
        "Created project %s beta=%s language=%s",
        project_id,
        account_id,
        language,
    )
    return ProjectResponse(
        project_id=project_id,
        status="created",
        language=language,
        user_id=user_id,
        beta_account_id=account_id,
        title=title,
        message="Project created",
    )


@router.get(
    "",
    summary="列出当前 Beta 账号的项目",
    description="History：只返回当前 Session 对应 `beta_account_id` 的项目。",
)
async def list_projects(
    session: BetaSession = Depends(require_beta_session),
) -> list[dict[str, Any]]:
    account_id = session.beta_account_id or ""
    projects = db.list_projects_for_beta_account(account_id)
    projects = sorted(
        projects,
        key=lambda p: p.project_id,
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    for p in projects:
        job = db.get_job(p.active_job_id) if p.active_job_id else None
        status = p.status
        if (
            p.final_video
            and (
                not job
                or job.status == "completed"
                or (job.status == "error" and p.status != "error")
            )
        ):
            status = "completed"
        item = {
            "project_id": p.project_id,
            "title": p.title,
            "status": status,
            "brief": p.brief,
            "workspace_slug": (p.property_metadata or {}).get("workspace_slug"),
            "final_video": p.final_video,
            "active_job_id": p.active_job_id,
            "beta_account_id": p.beta_account_id,
        }
        if (
            p.status != "created"
            or (p.property_metadata or {}).get("workspace_slug")
            or p.final_video
            or p.video_url
            or p.active_job_id
        ):
            items.append(item)
    return items


@router.get(
    "/{project_id}",
    summary="查看项目详情",
    description="用 `project_id` 查看 brief、语言、视频路径、成片路径、当前状态。",
)
async def get_project(
    project_id: str,
    session: BetaSession = Depends(require_beta_session),
) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)
    return project.model_dump()


@router.post(
    "/{project_id}/upload",
    response_model=ProjectResponse,
    tags=["③ 上传视频"],
    summary="上传视频（挂在项目路径下）",
    description="与 `POST /api/upload` 相同，只是把 `project_id` 写在 URL 里。",
)
async def upload_video(
    project_id: str,
    file: UploadFile = File(...),
    session: BetaSession = Depends(require_write_session),
) -> ProjectResponse:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)
    await save_project_video(project_id, file)
    return ProjectResponse(
        project_id=project_id,
        status="video_uploaded",
        message="Video uploaded",
    )


@router.post(
    "/{project_id}/produce",
    response_model=ProjectResponse,
    tags=["④ 生成视频"],
    summary="开始生成（快捷方式）",
    description="等同于 `POST /api/jobs`。返回 `job_id` 后去查询进度。",
)
async def start_production(
    project_id: str,
    session: BetaSession = Depends(require_write_session),
) -> ProjectResponse:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)

    job = _enqueue_generate(project)
    if _should_run_job_in_api(project):
        start_job_task(job)
    return ProjectResponse(
        project_id=project_id,
        status="queued",
        job_id=job.job_id,
        message="Production queued — poll GET /api/jobs/{job_id}",
    )


@router.post(
    "/{project_id}/cancel",
    summary="取消当前生成任务",
    description="网页点 ✕ 时调用。任务变 cancelled，Mac Worker 会停掉并去接下单。",
)
async def cancel_project_job(
    project_id: str,
    session: BetaSession = Depends(require_write_session),
) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)
    job_id = project.active_job_id
    if not job_id:
        return {
            "project_id": project_id,
            "job_id": None,
            "status": "cancelled",
            "message": "No active job",
        }
    updated = mark_job_cancelled(job_id)
    logger.info("User cancelled project %s job %s", project_id, job_id)
    return {
        "project_id": project_id,
        "job_id": job_id,
        "status": updated.status if updated else "cancelled",
        "message": "Cancelled",
    }


@router.get(
    "/{project_id}/status",
    summary="查看项目进度（前端每 3s 轮询）",
    description=(
        "返回 SaaS 进度字段：`status` / `stage` / `progress` / `video_url`。\n\n"
        "`status=processing` 表示 Worker 或本地 pipeline 正在跑。"
    ),
)
async def get_project_status(
    project_id: str,
    session: BetaSession = Depends(require_beta_session),
) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)

    job = db.get_job(project.active_job_id) if project.active_job_id else None
    job_status = job.status if job else None
    missing_active_job = (
        project.status in ("processing", "queued", "running")
        and (not project.active_job_id or job is None)
    )

    kind = (job.kind if job else "create") or "create"
    progress = int(job.progress) if job else 0
    stage = (job.stage if job else "") or ""
    looks_finished = progress >= 100 and (
        bool(project.final_video)
        or bool(job and (job.output_url or job.final_video))
    )
    if (
        project.status == "completed"
        or (job_status == "completed" and kind in ("create", "export"))
        or (
            bool(project.final_video)
            and job_status == "completed"
            and kind in ("script_update", "audio_offset")
        )
        or (bool(project.final_video) and job is None)
        or (kind in ("create", "export") and looks_finished)
    ):
        public_status = "completed"
    elif missing_active_job or job_status == "error" or project.status == "error":
        public_status = "error"
    elif job_status == "cancelled":
        public_status = "cancelled"
    elif job_status == "waiting":
        public_status = "waiting"
    elif job_status == "running" or project.status in ("processing", "queued", "running"):
        public_status = "processing"
    else:
        public_status = project.status

    meta = project.property_metadata or {}
    video_url = None
    download_url = None
    if public_status == "completed":
        video_url = (job.output_url if job else None) or project.final_video
        if video_url and str(video_url).startswith("r2://"):
            try:
                from backend import r2 as r2_mod

                _bucket, key = r2_mod.parse_r2_uri(str(video_url))
                download_url = r2_mod.generate_download_url(key, expires_in=3600)
            except Exception:  # noqa: BLE001
                download_url = None

    return {
        "project_id": project_id,
        "title": project.title or "",
        "brief": project.brief or "",
        "status": public_status,
        "stage": stage or ("Completed" if public_status == "completed" else ""),
        "progress": 100 if public_status == "completed" else progress,
        "video_url": video_url,
        "download_url": download_url,
        "job_id": project.active_job_id,
        "job_kind": job.kind if job else None,
        "workspace_slug": meta.get("workspace_slug"),
        "beta_account_id": project.beta_account_id,
        "pipeline_status": project.status,
        "job_status": job_status,
        "final_video": project.final_video,
        "error": (
            "The active generation job could not be found. Retry generation to queue a fresh run."
            if missing_active_job
            else (job.error if job and job.error else project.error) or ""
        ),
    }


@router.get(
    "/{project_id}/state",
    summary="查看项目完整快照",
    description="返回服务层项目对象（不是内部 Agent 的 ProjectState）。",
)
async def get_project_state(
    project_id: str,
    session: BetaSession = Depends(require_beta_session),
) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)
    return project.model_dump()


@router.get(
    "/{project_id}/result",
    tags=["④ 生成视频"],
    summary="获取成片结果",
    description="仅当状态为 `completed` 时可用。返回成片文件路径。",
)
async def get_project_result(
    project_id: str,
    session: BetaSession = Depends(require_beta_session),
) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_project_access(project, session)
    if project.status != "completed" or not project.final_video:
        raise HTTPException(
            status_code=400,
            detail=f"Production not completed. Current status: {project.status}",
        )
    return {
        "project_id": project_id,
        "status": "completed",
        "output_path": project.final_video,
        "final_video": project.final_video,
    }
