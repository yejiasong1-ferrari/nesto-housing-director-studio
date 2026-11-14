"""Helpers to create / bridge SaaS (Supabase) jobs for create + Studio revise/export."""

from __future__ import annotations

from typing import Literal, Optional

from backend.database import db
from backend.models import Job, Project
from backend.progress import ProgressCallback, make_db_progress_updater

JobKind = Literal["create", "script_update", "audio_offset", "export"]


def enqueue_job(
    project: Project,
    *,
    kind: JobKind = "create",
    stage: str = "Queued",
    progress: int = 0,
    status: str = "waiting",
    input_url: Optional[str] = None,
) -> Job:
    """Create a SaaS job row and attach it as the project's active job."""
    inp = input_url or project.video_url or project.video_path
    job = Job(
        job_id=db.new_id("job_"),
        project_id=project.project_id,
        kind=kind,
        status=status,  # type: ignore[arg-type]
        stage=stage,
        progress=progress,
        input_url=inp,
    )
    db.create_job(job)

    project.active_job_id = job.job_id
    if status == "waiting":
        project.status = "queued"
    elif status in ("running", "processing"):
        project.status = "processing"
    project.error = ""
    db.save_project(project)
    return job


def bridge_progress(job_id: str) -> ProgressCallback:
    return make_db_progress_updater(job_id)


def mark_job_completed(
    job_id: str,
    *,
    output_url: Optional[str] = None,
    workspace_slug: Optional[str] = None,
    workspace_r2_prefix: Optional[str] = None,
    complete_project: Optional[bool] = None,
) -> None:
    job = db.get_job(job_id)
    if not job:
        return
    if job.status == "cancelled":
        return
    job.status = "completed"
    job.stage = "Completed"
    job.progress = 100
    if output_url:
        job.output_url = output_url
        job.final_video = output_url
    job.error = ""
    db.save_job(job)

    project = db.get_project(job.project_id)
    if not project:
        return

    if complete_project is None:
        complete_project = job.kind in ("create", "export")

    if output_url:
        project.final_video = output_url
    project.error = ""
    if complete_project:
        project.status = "completed"
    elif project.status not in ("completed", "error"):
        project.status = "processing"
    if workspace_slug or workspace_r2_prefix:
        meta = dict(project.property_metadata or {})
        if workspace_slug:
            meta["workspace_slug"] = workspace_slug
        if workspace_r2_prefix:
            meta["workspace_r2_prefix"] = workspace_r2_prefix.rstrip("/")
        project.property_metadata = meta
    db.save_project(project)


def mark_job_cancelled(job_id: str, reason: str = "Cancelled by user") -> Optional[Job]:
    """Stop a waiting/running job so the Mac Worker can take the next one."""
    job = db.get_job(job_id)
    if not job:
        return None
    if job.status in ("completed", "cancelled"):
        return job
    job.status = "cancelled"
    job.stage = "Cancelled"
    job.error = reason
    db.save_job(job)
    project = db.get_project(job.project_id)
    if project and project.status not in ("completed",):
        project.status = "video_uploaded" if (project.video_url or project.video_path) else "created"
        project.error = ""
        db.save_project(project)
    return job


def mark_job_failed(job_id: str, error: str) -> None:
    job = db.get_job(job_id)
    if not job:
        return
    if job.status == "cancelled":
        return
    job.status = "error"
    job.stage = "Failed"
    job.error = error
    db.save_job(job)
    project = db.get_project(job.project_id)
    if project:
        project.status = "error"
        project.error = error
        db.save_project(project)


def attach_studio_saas_job(
    slug: str,
    kind: JobKind,
    *,
    queue_for_worker: bool = False,
) -> Optional[tuple[str, ProgressCallback]]:
    """If this workspace is linked to a SaaS project, create a SaaS job.

    ``queue_for_worker=True`` leaves the job ``waiting`` for the Mac Worker
    (used for export / render). Otherwise status starts as ``running`` for
    in-process Railway revise tasks.
    """
    project = db.find_project_by_workspace_slug(slug)
    if not project:
        return None
    job = enqueue_job(
        project,
        kind=kind,
        stage="Queued" if queue_for_worker else "Starting",
        progress=0 if queue_for_worker else 1,
        status="waiting" if queue_for_worker else "running",
        input_url=project.video_url or project.video_path,
    )
    return job.job_id, bridge_progress(job.job_id)
