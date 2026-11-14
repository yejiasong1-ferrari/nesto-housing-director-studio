"""Job API — queue, Worker claim, progress updates, and local generate_video."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.api.invite import require_beta_session, require_write_session
from backend.database import db
from backend.invite_db import BetaSession
from backend.models import (
    CompleteJobBody,
    CreateJobBody,
    Job,
    JobResponse,
    Project,
    UpdateJobBody,
    WorkerJobPayload,
)
from backend.progress import make_db_progress_updater
from backend.saas_jobs import (
    enqueue_job,
    mark_job_cancelled,
    mark_job_completed,
    mark_job_failed,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["④ 生成视频"])


def require_worker_key(
    x_worker_key: Optional[str] = Header(default=None, alias="X-Worker-Key"),
) -> None:
    """Protect worker claim/update routes when WORKER_API_KEY is configured."""
    expected = (os.getenv("WORKER_API_KEY") or "").strip()
    if not expected:
        return
    if not x_worker_key or x_worker_key.strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid worker key")


def _enqueue_generate(project: Project) -> Job:
    """Create a waiting job and attach it to the project (caller starts the task)."""
    if not project.video_path and not project.video_url:
        raise HTTPException(
            status_code=400,
            detail="Upload a video before starting a job (local path or R2 video_url)",
        )
    if project.status == "running":
        raise HTTPException(status_code=409, detail="A job is already running for this project")

    return enqueue_job(
        project,
        kind="create",
        stage="Queued",
        progress=0,
        status="waiting",
        input_url=project.video_url or project.video_path,
    )


def _job_response(job: Job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        kind=job.kind,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        input_url=job.input_url,
        output_url=job.output_url or job.final_video,
        final_video=job.output_url or job.final_video,
        error=job.error,
    )


def _worker_payload(job: Job, project: Project) -> WorkerJobPayload:
    meta = project.property_metadata or {}
    return WorkerJobPayload(
        id=job.job_id,
        job_id=job.job_id,
        project_id=project.project_id,
        kind=job.kind,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        video_url=project.video_url or job.input_url,
        video_path=project.video_path,
        input_url=job.input_url or project.video_url or project.video_path,
        brief=project.brief or "",
        language=project.language or "zh",
        user_id=project.beta_account_id or project.user_id,
        title=project.title or "",
        workspace_slug=meta.get("workspace_slug"),
    )


def _normalize_worker_status(status: Optional[str]) -> Optional[str]:
    if not status:
        return None
    s = status.strip().lower()
    if s == "processing":
        return "running"
    if s in ("waiting", "running", "completed", "error", "cancelled"):
        return s
    raise HTTPException(status_code=400, detail=f"Invalid status: {status}")


async def run_generate_video_job(job_id: str) -> None:
    """Background worker: waiting → running → completed|error via generate_video()."""
    job = db.get_job(job_id)
    project = db.get_project(job.project_id) if job else None
    if not job or not project:
        return
    if not project.video_path:
        mark_job_failed(
            job_id,
            "No local video_path. R2 uploads create waiting jobs for a Worker "
            "to download from video_url before generate_video().",
        )
        return

    job.status = "running"
    job.stage = "Starting"
    job.progress = 5
    project.status = "processing"
    db.save_job(job)
    db.save_project(project)

    on_progress = make_db_progress_updater(job_id)

    try:
        from backend.ai_director import generate_video

        final = await generate_video(
            video_path=project.video_path,
            brief=project.brief,
            language=project.language,
            on_progress=on_progress,
        )

        dest = db.project_dir(project.project_id) / "final_video.mp4"
        if Path(final).resolve() != dest.resolve():
            shutil.copy2(final, dest)

        # Prefer workspace slug from path parents (storage/properties/<slug>/...)
        workspace_slug = None
        try:
            parts = Path(final).parts
            if "properties" in parts:
                idx = parts.index("properties")
                if idx + 1 < len(parts):
                    workspace_slug = parts[idx + 1]
        except Exception:  # noqa: BLE001
            workspace_slug = None

        mark_job_completed(
            job_id,
            output_url=str(dest.resolve()),
            workspace_slug=workspace_slug,
        )
    except Exception as exc:
        logger.exception("generate_video job %s failed", job_id)
        mark_job_failed(job_id, str(exc))


def start_job_task(job: Job) -> None:
    """Fire-and-forget asyncio task for a newly enqueued local job."""
    asyncio.create_task(run_generate_video_job(job.job_id))


def _should_run_job_in_api(project: Project) -> bool:
    """Only dev/local API should run the heavy video pipeline in-process."""
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"):
        return False
    if os.getenv("DISABLE_IN_PROCESS_VIDEO_JOBS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return False
    return bool(project.video_path)


@router.post(
    "",
    response_model=JobResponse,
    summary="③ 开始生成成片",
    description=(
        "传入已上传视频的 `project_id`。\n\n"
        "- 本地 `video_path`：Backend 进程内调用 `generate_video()`（带细粒度 progress）。\n"
        "- 仅有 R2 `video_url`：任务保持 `waiting`，由 Mac/GPU Worker 认领。"
    ),
)
async def create_job(
    body: CreateJobBody,
    session: BetaSession = Depends(require_write_session),
) -> JobResponse:
    project = db.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.beta_account_id and project.beta_account_id != session.beta_account_id:
        raise HTTPException(status_code=404, detail="Project not found")

    job = _enqueue_generate(project)
    if _should_run_job_in_api(project):
        start_job_task(job)
    return _job_response(job)


@router.get(
    "",
    response_model=List[JobResponse],
    summary="列出任务（Worker 可轮询 waiting）",
    description="可选查询参数 `status=waiting`，供后续 Worker 拉取队列。",
)
async def list_jobs(
    status: Optional[str] = None,
    _worker: None = Depends(require_worker_key),
) -> List[JobResponse]:
    return [_job_response(j) for j in db.list_jobs(status=status)]


@router.get(
    "/next",
    response_model=Optional[WorkerJobPayload],
    summary="Worker 认领下一个 waiting 任务",
    description=(
        "原子认领最旧的 `waiting` 任务 → `running`。\n\n"
        "无任务时返回 `null`（HTTP 200）。多 Worker 下用行锁避免重复认领。"
    ),
)
async def next_job(_worker: None = Depends(require_worker_key)) -> Optional[WorkerJobPayload]:
    try:
        db.requeue_stale_running_jobs()
    except Exception as exc:  # noqa: BLE001 — still try to claim waiting work
        logger.warning("stale job requeue skipped: %s", exc)
    claimed = db.claim_next_job()
    if not claimed:
        return None
    job, project = claimed
    logger.info("Worker claimed job %s (project %s)", job.job_id, project.project_id)
    return _worker_payload(job, project)


@router.post(
    "/update",
    response_model=JobResponse,
    summary="Worker 上报进度 / 阶段",
)
async def update_job(
    body: UpdateJobBody,
    _worker: None = Depends(require_worker_key),
) -> JobResponse:
    job = db.get_job(body.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    project = db.get_project(job.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # User / admin cancel — do not let workers revive or overwrite the row.
    if job.status == "cancelled":
        return _job_response(job)

    if body.stage is not None:
        job.stage = body.stage
    if body.progress is not None:
        job.progress = max(0, min(100, int(body.progress)))
    if body.error is not None:
        job.error = body.error

    status = _normalize_worker_status(body.status)
    if status:
        job.status = status  # type: ignore[assignment]
        if status == "running":
            project.status = "processing"
        elif status == "completed":
            project.status = "completed"
            job.progress = max(job.progress, 100)
            job.stage = job.stage or "Completed"
            if job.output_url or job.final_video:
                project.final_video = job.output_url or job.final_video
        elif status == "error":
            project.status = "error"
            if body.error:
                project.error = body.error
        elif status == "waiting":
            project.status = "queued"
    elif job.status in ("waiting", "running") and (body.stage or body.progress is not None):
        job.status = "running"
        project.status = "processing"

    db.save_job(job)
    db.save_project(project)
    return _job_response(job)


@router.post(
    "/complete",
    response_model=JobResponse,
    summary="Worker 标记任务完成（或失败）",
)
async def complete_job(
    body: CompleteJobBody,
    _worker: None = Depends(require_worker_key),
) -> JobResponse:
    job = db.get_job(body.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if body.error:
        mark_job_failed(body.job_id, body.error)
    else:
        if job.status == "cancelled":
            return _job_response(job)
        final = (body.final_r2_uri or body.final_video or "").strip()
        if not final:
            raise HTTPException(
                status_code=400,
                detail="Provide final_r2_uri or final_video when completing successfully",
            )
        mark_job_completed(
            body.job_id,
            output_url=final,
            workspace_slug=body.workspace_slug,
            workspace_r2_prefix=body.workspace_r2_prefix,
        )

    updated = db.get_job(body.job_id)
    assert updated is not None
    logger.info("Job %s → %s", updated.job_id, updated.status)
    return _job_response(updated)


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
    summary="取消任务（网页 ✕）",
    description="将 waiting/running 任务标为 cancelled。Worker 下一拍会停掉并去接下单。",
)
async def cancel_job(
    job_id: str,
    session: BetaSession = Depends(require_write_session),
) -> JobResponse:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    project = db.get_project(job.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.beta_account_id and project.beta_account_id != session.beta_account_id:
        raise HTTPException(status_code=404, detail="Job not found")
    updated = mark_job_cancelled(job_id) or job
    logger.info("User cancelled job %s (project %s)", job_id, project.project_id)
    return _job_response(updated)


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="④ 查询任务进度",
    description=(
        "常见状态：`waiting` → `running` → `completed`（或 `error`）。\n\n"
        "完成后看 `output_url` / `final_video` 字段。"
    ),
)
async def get_job(job_id: str) -> JobResponse:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response(job)
