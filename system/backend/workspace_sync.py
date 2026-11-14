"""Push / refresh Studio workspaces between Railway disk and R2."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from backend.r2 import download_prefix, r2_configured, upload_file
from backend.tools.property_workspace import STORAGE_ROOT
from backend.workspace_hydrate import _normalize_property_json, resolve_workspace_r2_prefix

logger = logging.getLogger(__name__)

_SKIP_DIR_NAMES = {"frames", "keyframes", "__pycache__"}
_SKIP_FILE_NAMES = {"final_video.mp4"}


def _content_type(path: Path) -> str:
    return {
        ".json": "application/json",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".mp4": "video/mp4",
        ".m4a": "audio/mp4",
    }.get(path.suffix.lower(), "application/octet-stream")


def push_workspace_to_r2(slug: str, prefix: str) -> int:
    """Upload local ``STORAGE_ROOT/slug`` essentials to ``prefix``. Returns file count."""
    if not r2_configured():
        raise RuntimeError("R2 is not configured")
    root = STORAGE_ROOT / slug
    if not (root / "property.json").exists():
        raise FileNotFoundError(f"Workspace missing: {slug}")

    prefix = prefix.strip().rstrip("/")
    uploaded = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in _SKIP_DIR_NAMES for part in rel_parts):
            continue
        if path.name in _SKIP_FILE_NAMES and (root / "output" / "final_video_v2.mp4").exists():
            continue
        rel = path.relative_to(root).as_posix()
        upload_file(path, f"{prefix}/{rel}", content_type=_content_type(path))
        uploaded += 1

    source = root / "source.mp4"
    video_name = ""
    try:
        import json

        meta = json.loads((root / "property.json").read_text(encoding="utf-8"))
        video_name = str(meta.get("video_name") or "")
        vp = meta.get("video_path")
        if vp and Path(str(vp)).exists() and Path(str(vp)).resolve() != source.resolve():
            upload_file(vp, f"{prefix}/source.mp4", content_type="video/mp4")
            uploaded += 1
        elif video_name and (root / video_name).exists():
            upload_file(root / video_name, f"{prefix}/source.mp4", content_type="video/mp4")
            uploaded += 1
        elif source.exists():
            # already uploaded via rglob if under root
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("source upload skipped: %s", exc)

    logger.info("Pushed workspace %s → %s (%s files)", slug, prefix, uploaded)
    return uploaded


def refresh_workspace_from_r2(slug: str, prefix: Optional[str] = None) -> Path:
    """Replace local workspace from R2 (used after Mac Worker export)."""
    root = STORAGE_ROOT / slug
    pfx = (prefix or resolve_workspace_r2_prefix(slug) or "").strip().rstrip("/")
    if not pfx:
        raise FileNotFoundError(f"No R2 prefix for workspace {slug}")
    if root.exists():
        shutil.rmtree(root)
    count = download_prefix(pfx, root)
    if count == 0 or not (root / "property.json").exists():
        raise FileNotFoundError(f"Failed to refresh workspace {slug} from {pfx}")
    _normalize_property_json(root)
    logger.info("Refreshed workspace %s from R2 (%s files)", slug, count)
    return root
