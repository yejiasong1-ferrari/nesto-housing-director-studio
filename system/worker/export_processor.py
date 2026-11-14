"""Export / regenerate final video for a claimed SaaS export job."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api_client import JobCancelled, complete_job, update_job
from uploader import upload_final
from workspace_upload import upload_studio_workspace

logger = logging.getLogger(__name__)

WORKER_ROOT = Path(__file__).resolve().parent
REPO_ROOT = WORKER_ROOT.parent.parent
STORAGE_ROOT = REPO_ROOT / "storage" / "properties"


def process_export(job: dict) -> Path:
    """Pull latest workspace from R2 → render → upload final + workspace."""
    job_id = job["id"]
    slug = (job.get("workspace_slug") or "").strip()
    if not slug:
        raise RuntimeError("export job missing workspace_slug")

    def update_progress(stage: str, progress: int) -> None:
        try:
            update_job(job_id, stage, progress, status="running")
            print(f"  [{progress:3d}%] {stage}")
        except JobCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("progress update failed: %s", exc)

    try:
        update_progress("Syncing workspace", 10)
        from backend.r2 import download_prefix, r2_configured
        from backend.workspace_hydrate import _normalize_property_json

        if not r2_configured():
            raise RuntimeError("R2 is not configured on worker")

        user_id = job.get("user_id") or "anonymous"
        project_id = job.get("project_id") or "unknown"
        prefix = f"users/{user_id}/projects/{project_id}/workspace"

        ws_root = STORAGE_ROOT / slug
        if ws_root.exists():
            shutil.rmtree(ws_root)
        count = download_prefix(prefix, ws_root)
        if count == 0 or not (ws_root / "property.json").exists():
            raise RuntimeError(f"No workspace files under R2 prefix {prefix}")
        _normalize_property_json(ws_root)

        update_progress("Rendering", 25)
        from backend.tools.property_workspace import resolve_workspace_by_slug
        from backend.workflow.jobs import Job as StudioJob, StageState
        from backend.workflow.orchestrator import run_export
        from backend.workspace_paths import (
            materialize_workspace_audio_paths,
            rewrite_workspace_media_paths,
        )

        rewrite_workspace_media_paths(ws_root)
        materialize_workspace_audio_paths(ws_root)

        ws = resolve_workspace_by_slug(slug)
        studio_job = StudioJob(
            id=f"worker-{job_id}",
            slug=slug,
            kind="export",
            stages=[
                StageState("prepare", "Loading edited project"),
                StageState("render", "Rendering final video"),
                StageState("finalize", "Saving output"),
            ],
        )

        def on_progress(stage: str, progress: int) -> None:
            # Cap below 100 — uploads still run after render.
            mapped = min(90, 25 + int(max(0, min(100, progress)) * 0.65))
            update_progress(stage or "Rendering", mapped)

        studio_job.on_progress = on_progress
        asyncio.run(run_export(studio_job, ws))
        if studio_job.status == "error":
            raise RuntimeError(studio_job.error or "Export failed")
        if studio_job.status == "cancelled":
            raise RuntimeError("Export cancelled")

        final_path = ws.final_video_v2_path
        if not final_path.exists():
            final_path = ws.final_video_path
        if not final_path.exists():
            raise RuntimeError("Export finished but final video missing")

        source = None
        meta_path = ws_root / "property.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            vp = meta.get("video_path")
            if vp and Path(vp).exists():
                source = Path(vp)
            elif (ws_root / "source.mp4").exists():
                source = ws_root / "source.mp4"

        local_final = final_path
        update_progress("Uploading final & Studio", 92)
        with ThreadPoolExecutor(max_workers=2) as pool:
            final_future = pool.submit(upload_final, job, local_final)
            workspace_future = pool.submit(
                upload_studio_workspace,
                job,
                ws_root,
                source_video=source,
            )
            r2_uri = final_future.result()
            workspace_r2_prefix = workspace_future.result()

        complete_job(
            job_id,
            final_r2_uri=r2_uri,
            final_video=str(local_final),
            workspace_slug=slug,
            workspace_r2_prefix=workspace_r2_prefix,
        )
        print("  [100%] Export completed")
        logger.info("Export job %s completed → %s", job_id, r2_uri)
        return local_final
    except JobCancelled:
        logger.info("Export job %s cancelled — releasing worker", job_id)
        print(f"Cancelled: {job_id}")
        raise
    except Exception as exc:
        logger.exception("Export job %s failed", job_id)
        try:
            complete_job(job_id, error=str(exc))
        except Exception:  # noqa: BLE001
            try:
                update_job(job_id, "Failed", 100, status="error", error=str(exc))
            except JobCancelled:
                raise
        raise
