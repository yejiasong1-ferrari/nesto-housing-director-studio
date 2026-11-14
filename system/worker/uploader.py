"""Upload final MP4 to Cloudflare R2."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def upload_final(job: dict, local_path: Path) -> str:
    """Upload ``final.mp4`` under the project output prefix; return ``r2://`` URI."""
    from backend.r2 import upload_file

    user_id = job.get("user_id") or "anonymous"
    project_id = job.get("project_id") or "unknown"
    key = f"users/{user_id}/projects/{project_id}/output/final.mp4"
    uri = upload_file(local_path, key, content_type="video/mp4")
    logger.info("Uploaded final → %s", uri)
    return uri
