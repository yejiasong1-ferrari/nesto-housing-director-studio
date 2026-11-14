"""Download source video from Cloudflare R2 (or copy local path)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def download_input(job: dict, work_dir: Path) -> Path:
    """Resolve job video into ``work_dir/input`` (preserves extension when possible)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    video_url = (job.get("video_url") or "").strip()
    video_path = (job.get("video_path") or "").strip()

    if video_path:
        src = Path(video_path).expanduser().resolve()
        if src.exists():
            dest = work_dir / src.name
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            logger.info("Using local video %s", dest)
            return dest

    if not video_url:
        raise FileNotFoundError("Job has neither video_url nor usable video_path")

    # Infer filename from key
    name = video_url.rstrip("/").split("/")[-1] or "input.mov"
    if "?" in name:
        name = name.split("?", 1)[0]
    dest = work_dir / name

    from backend.r2 import download_object

    download_object(video_url, dest)
    return dest
