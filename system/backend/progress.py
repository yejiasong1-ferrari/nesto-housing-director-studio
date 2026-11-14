"""Shared progress reporting for SaaS jobs + Studio in-memory jobs.

Pipeline stages call ``on_progress(stage, progress)``; Worker / Studio /
local runners persist that into Supabase or the Studio job store.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Callable, Optional


class JobCancelled(Exception):
    """User or admin cancelled the job; Worker should stop and take the next one."""


_cancel_check: ContextVar[Optional[Callable[[], None]]] = ContextVar(
    "nesto_job_cancel_check", default=None
)


def set_cancel_checker(fn: Optional[Callable[[], None]]) -> Token:
    return _cancel_check.set(fn)


def reset_cancel_checker(token: Token) -> None:
    _cancel_check.reset(token)


def raise_if_job_cancelled() -> None:
    fn = _cancel_check.get()
    if fn:
        fn()

# (stage_name, status) → (progress 0–100, human label)
CREATE_STAGE_PROGRESS: dict[tuple[str, str], tuple[int, str]] = {
    ("vision", "running"): (15, "Vision Analysis"),
    ("vision", "done"): (28, "Vision Analysis"),
    ("story", "running"): (40, "Script & Voice"),
    ("story", "done"): (58, "Script & Voice"),
    ("editing", "running"): (70, "Editing"),
    ("editing", "done"): (78, "Editing"),
    ("evaluation", "running"): (80, "Quality evaluation"),
    # Cap below 100 — Worker still uploads final + studio workspace before complete_job.
    ("evaluation", "done"): (90, "Quality pass"),
}

SCRIPT_UPDATE_PROGRESS: dict[tuple[str, str], tuple[int, str]] = {
    ("apply", "running"): (15, "Saving Script"),
    ("apply", "done"): (30, "Saving Script"),
    ("voice", "running"): (55, "Voice Generation"),
    ("voice", "done"): (85, "Voice Generation"),
    ("subtitle", "done"): (95, "Subtitles"),
}

AUDIO_OFFSET_PROGRESS: dict[tuple[str, str], tuple[int, str]] = {
    ("apply", "running"): (40, "Adjusting Audio"),
    ("apply", "done"): (100, "Completed"),
}

EXPORT_PROGRESS: dict[tuple[str, str], tuple[int, str]] = {
    ("prepare", "running"): (15, "Preparing Export"),
    ("prepare", "done"): (30, "Preparing Export"),
    ("render", "running"): (55, "Rendering"),
    ("render", "done"): (90, "Rendering"),
    ("finalize", "running"): (95, "Finalizing"),
    ("finalize", "done"): (100, "Completed"),
}

KIND_MAP = {
    "create_project": CREATE_STAGE_PROGRESS,
    "create": CREATE_STAGE_PROGRESS,
    "script_update": SCRIPT_UPDATE_PROGRESS,
    "audio_offset": AUDIO_OFFSET_PROGRESS,
    "export": EXPORT_PROGRESS,
}

ProgressCallback = Callable[[str, int], None]


def resolve_stage_progress(
    kind: str,
    stage_name: str,
    status: str,
) -> Optional[tuple[int, str]]:
    table = KIND_MAP.get(kind) or CREATE_STAGE_PROGRESS
    return table.get((stage_name, status))


def make_http_progress_updater(job_id: str, update_fn: Callable[..., object]) -> ProgressCallback:
    """Wrap a function ``update_fn(job_id, stage, progress)`` as a callback."""

    def _cb(stage: str, progress: int) -> None:
        update_fn(job_id, stage, progress)

    return _cb


def make_db_progress_updater(job_id: str) -> ProgressCallback:
    """Persist stage/progress onto the SaaS jobs row (+ project processing)."""

    def _cb(stage: str, progress: int) -> None:
        from backend.database import db

        job = db.get_job(job_id)
        if not job:
            return
        if job.status == "cancelled":
            raise JobCancelled("Cancelled by user")
        job.stage = stage
        job.progress = max(0, min(100, int(progress)))
        if job.status in ("waiting", "running") or job.status == "processing":  # type: ignore[comparison-overlap]
            job.status = "running"
        if progress >= 100 and job.status == "running":
            # Leave final completed mark to complete_job / runner
            pass
        db.save_job(job)
        project = db.get_project(job.project_id)
        if project and project.status not in ("completed", "error"):
            project.status = "processing"
            project.active_job_id = job.job_id
            db.save_project(project)

    return _cb
