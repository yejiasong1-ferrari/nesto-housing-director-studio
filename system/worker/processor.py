"""Run AI Director for a claimed job and report fine-grained progress."""

from __future__ import annotations

import asyncio
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api_client import JobCancelled, complete_job, raise_if_cancelled, update_job
from downloader import download_input
from uploader import upload_final
from workspace_upload import upload_studio_workspace

logger = logging.getLogger(__name__)

WORKER_ROOT = Path(__file__).resolve().parent
TEMP_ROOT = WORKER_ROOT / "temp"

# Pipeline may briefly report high progress; never claim 100 before uploads finish.
_PIPELINE_PROGRESS_CAP = 90


def _workspace_slug_from_path(path: Path) -> str | None:
    parts = path.parts
    if "properties" in parts:
        idx = parts.index("properties")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def _unique_source_name(job: dict, local_video: Path) -> str:
    """Stable unique stem so normalize doesn't collapse every job to ``source-ai``."""
    from backend.tools.property_workspace import slug_from_name

    title = (job.get("title") or "").strip()
    base = slug_from_name(title or local_video.name)
    job_id = str(job.get("id") or "job")
    suffix = job_id.replace("job_", "")[-8:]
    return f"{base}-{suffix}" if suffix else base


def process(job: dict) -> Path:
    """Download → generate_video(on_progress) → upload → mark completed.

    Also handles ``kind=export`` (Studio regenerate) via ``process_export``.
    """
    kind = (job.get("kind") or "create").strip().lower()
    if kind == "export":
        from export_processor import process_export

        return process_export(job)

    job_id = job["id"]
    work_dir = TEMP_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    def update_progress(stage: str, progress: int) -> None:
        try:
            update_job(job_id, stage, progress, status="running")
            print(f"  [{progress:3d}%] {stage}")
        except JobCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("progress update failed: %s", exc)

    def pipeline_progress(stage: str, progress: int) -> None:
        update_progress(stage, min(int(progress), _PIPELINE_PROGRESS_CAP))

    try:
        update_progress("Downloading", 5)
        local_video = download_input(job, work_dir)

        update_progress("Preparing video", 8)
        from backend.tools.video_normalize import (
            VideoTooLargeError,
            VideoTooLongError,
            normalize_for_ai,
        )

        source_stem = _unique_source_name(job, local_video)
        try:
            local_video = normalize_for_ai(
                local_video,
                work_dir / f"{source_stem}.mp4",
            )
        except (VideoTooLongError, VideoTooLargeError) as exc:
            raise RuntimeError(str(exc)) from exc

        brief = job.get("brief") or ""
        language = job.get("language") or "zh"

        from backend.ai_director import generate_video
        from backend.progress import reset_cancel_checker, set_cancel_checker

        cancel_token = set_cancel_checker(lambda: raise_if_cancelled(job_id))
        try:
            final = asyncio.run(
                generate_video(
                    video_path=local_video,
                    brief=brief,
                    language=language,
                    on_progress=pipeline_progress,
                )
            )
        finally:
            reset_cancel_checker(cancel_token)
        final_path = Path(final).resolve()
        workspace_slug = _workspace_slug_from_path(final_path)

        # Upload directly from the rendered path. Copying a 100MB+ final into
        # worker/temp adds disk I/O but no durability or quality benefit.
        local_final = final_path
        workspace_r2_prefix = None
        ws_root = None
        if workspace_slug:
            ws_root = final_path.parent.parent  # .../properties/<slug>/output/<file>
            if ws_root.name == "output":
                ws_root = ws_root.parent
            # Prefer properties/<slug> when final lives under storage/properties
            parts = final_path.parts
            if "properties" in parts:
                idx = parts.index("properties")
                if idx + 1 < len(parts):
                    ws_root = Path(*parts[: idx + 2])

        update_progress("Uploading final & Studio", 94)
        with ThreadPoolExecutor(max_workers=2) as pool:
            final_future = pool.submit(upload_final, job, local_final)
            workspace_future = (
                pool.submit(
                    upload_studio_workspace,
                    job,
                    ws_root,
                    source_video=local_video,
                )
                if ws_root is not None
                else None
            )
            r2_uri = final_future.result()
            if workspace_future is not None:
                try:
                    workspace_r2_prefix = workspace_future.result()
                except Exception as exc:  # noqa: BLE001 — final is still usable
                    logger.warning("studio workspace upload failed: %s", exc)

        complete_job(
            job_id,
            final_r2_uri=r2_uri,
            final_video=str(local_final),
            workspace_slug=workspace_slug,
            workspace_r2_prefix=workspace_r2_prefix,
        )
        # Do NOT call update_job(..., status="running") after complete —
        # that re-opens the job and blocks the frontend redirect.
        print("  [100%] Completed")
        logger.info("Job %s completed → %s (slug=%s)", job_id, r2_uri, workspace_slug)
        return local_final
    except JobCancelled:
        logger.info("Job %s cancelled — releasing worker", job_id)
        print(f"Cancelled: {job_id}")
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        try:
            complete_job(job_id, error=str(exc))
        except Exception:  # noqa: BLE001
            try:
                update_job(job_id, "Failed", 100, status="error", error=str(exc))
            except JobCancelled:
                raise
        raise
