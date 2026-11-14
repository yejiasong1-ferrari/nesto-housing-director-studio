"""Upload Studio workspace essentials to R2 so Railway can hydrate the editor."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Skip heavy frame dumps; Studio UI needs JSON + audio + renders + source.
_SKIP_DIR_NAMES = {"frames", "keyframes", "__pycache__"}
# The canonical final is already uploaded to .../output/final.mp4. Uploading
# either workspace render again wastes ~100MB and delays Studio availability.
_SKIP_FILE_NAMES = {"final_video.mp4", "final_video_v2.mp4", "final.mp4"}


def _content_type(path: Path) -> str:
    return {
        ".json": "application/json",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".mp4": "video/mp4",
        ".m4a": "audio/mp4",
    }.get(path.suffix.lower(), "application/octet-stream")


def _iter_studio_files(workspace: Path) -> Iterable[Path]:
    if not workspace.is_dir():
        return
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(workspace).parts
        if any(part in _SKIP_DIR_NAMES for part in rel_parts):
            continue
        if path.name in _SKIP_FILE_NAMES:
            continue
        yield path


def workspace_r2_prefix(user_id: str, project_id: str) -> str:
    return f"users/{user_id}/projects/{project_id}/workspace"


def upload_studio_workspace(
    job: dict,
    workspace_root: Path,
    *,
    source_video: Optional[Path] = None,
) -> Optional[str]:
    """Upload property workspace files under ``.../workspace/``. Returns R2 prefix."""
    from backend.r2 import upload_file

    user_id = job.get("user_id") or "anonymous"
    project_id = job.get("project_id") or "unknown"
    prefix = workspace_r2_prefix(user_id, project_id)
    workspace_root = workspace_root.resolve()

    uploads: list[tuple[Path, str, str]] = []
    for path in _iter_studio_files(workspace_root):
        rel = path.relative_to(workspace_root).as_posix()
        key = f"{prefix}/{rel}"
        uploads.append((path, key, _content_type(path)))

    if source_video and Path(source_video).exists():
        uploads.append((
            Path(source_video),
            f"{prefix}/source.mp4",
            "video/mp4",
        ))

    def _upload(item: tuple[Path, str, str]) -> None:
        path, key, content_type = item
        upload_file(path, key, content_type=content_type)

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(uploads)))) as pool:
        list(pool.map(_upload, uploads))

    uploaded = len(uploads)

    logger.info(
        "Uploaded studio workspace (%s files) → r2://…/%s/",
        uploaded,
        prefix,
    )
    return prefix if uploaded else None
