"""HTTP client: Worker ↔ Backend job queue."""

from __future__ import annotations

import os
import logging
from typing import Any, Optional

import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
JOB_FETCH_TIMEOUT = float(os.getenv("WORKER_JOB_FETCH_TIMEOUT", "5"))
JOB_CLAIM_TIMEOUT = float(os.getenv("WORKER_JOB_CLAIM_TIMEOUT", "20"))
JOB_UPDATE_TIMEOUT = float(os.getenv("WORKER_JOB_UPDATE_TIMEOUT", "30"))
JOB_COMPLETE_TIMEOUT = float(os.getenv("WORKER_JOB_COMPLETE_TIMEOUT", "120"))

logger = logging.getLogger(__name__)


from backend.progress import JobCancelled


def _worker_headers() -> dict[str, str]:
    key = (os.getenv("WORKER_API_KEY") or "").strip()
    return {"X-Worker-Key": key} if key else {}


def fetch_job(job_id: str) -> dict[str, Any]:
    """Read job row without claiming. Used to notice user cancel."""
    response = requests.get(
        f"{BACKEND_URL}/api/jobs/{job_id}",
        headers=_worker_headers(),
        timeout=JOB_FETCH_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def raise_if_cancelled(job_id: str, payload: Optional[dict[str, Any]] = None) -> None:
    try:
        data = payload if payload is not None else fetch_job(job_id)
    except requests.RequestException as exc:
        # Cancellation checks run before expensive LLM/TTS calls. A transient
        # Railway timeout must not fail the creative stage; only an explicit
        # ``cancelled`` row should stop the worker.
        logger.warning("cancel check skipped for %s: %s", job_id, exc)
        return
    if (data or {}).get("status") == "cancelled":
        raise JobCancelled(f"{job_id} cancelled")


def get_job() -> Optional[dict[str, Any]]:
    """Claim next waiting job via ``GET /api/jobs/next``. Returns None if idle."""
    response = requests.get(
        f"{BACKEND_URL}/api/jobs/next",
        headers=_worker_headers(),
        timeout=JOB_CLAIM_TIMEOUT,
    )
    if response.status_code != 200:
        response.raise_for_status()
    data = response.json()
    if not data:
        return None
    return data


def update_job(
    job_id: str,
    stage: str,
    progress: int,
    *,
    status: Optional[str] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": job_id,
        "stage": stage,
        "progress": progress,
    }
    if status is not None:
        payload["status"] = status
    if error is not None:
        payload["error"] = error
    response = requests.post(
        f"{BACKEND_URL}/api/jobs/update",
        headers=_worker_headers(),
        json=payload,
        timeout=JOB_UPDATE_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    raise_if_cancelled(job_id, data)
    return data


def complete_job(
    job_id: str,
    *,
    final_r2_uri: Optional[str] = None,
    final_video: Optional[str] = None,
    workspace_slug: Optional[str] = None,
    workspace_r2_prefix: Optional[str] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"job_id": job_id}
    if error:
        payload["error"] = error
    else:
        if final_r2_uri:
            payload["final_r2_uri"] = final_r2_uri
        if final_video:
            payload["final_video"] = final_video
        if workspace_slug:
            payload["workspace_slug"] = workspace_slug
        if workspace_r2_prefix:
            payload["workspace_r2_prefix"] = workspace_r2_prefix
    response = requests.post(
        f"{BACKEND_URL}/api/jobs/complete",
        headers=_worker_headers(),
        json=payload,
        timeout=JOB_COMPLETE_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()
