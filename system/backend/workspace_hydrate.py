"""Hydrate local Studio workspaces from R2 when Railway has no Mac disk."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from backend.database import db
from backend.r2 import download_prefix, r2_configured
from backend.tools.property_workspace import STORAGE_ROOT

logger = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(slug: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(slug)
        if lock is None:
            lock = threading.Lock()
            _locks[slug] = lock
        return lock


def _normalize_property_json(root: Path) -> None:
    meta_path = root / "property.json"
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return

    source = root / "source.mp4"
    video_name = str(meta.get("video_name") or "").strip()
    preferred = root / video_name if video_name else None
    if source.exists() and preferred and preferred.name != "source.mp4":
        if not preferred.exists():
            source.replace(preferred)
        meta["video_path"] = str(preferred.resolve())
    elif source.exists():
        meta["video_path"] = str(source.resolve())
    elif meta.get("video_path") and not Path(str(meta["video_path"])).exists():
        # Fall back to final render so source endpoint / resolve_workspace still work
        for candidate in (
            root / "output" / "final_video_v2.mp4",
            root / "output" / "final_video.mp4",
        ):
            if candidate.exists():
                meta["video_path"] = str(candidate.resolve())
                break

    paths = meta.get("paths")
    if isinstance(paths, dict):
        for key in list(paths.keys()):
            local = root / key
            if local.exists():
                paths[key] = str(local.resolve())
        meta["paths"] = paths

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        from backend.workspace_paths import rewrite_workspace_media_paths

        rewrite_workspace_media_paths(root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("audio path rewrite skipped: %s", exc)


def resolve_workspace_r2_prefix(slug: str) -> Optional[str]:
    project = db.find_project_by_workspace_slug(slug)
    if not project:
        return None
    meta = project.property_metadata or {}
    prefix = (meta.get("workspace_r2_prefix") or "").strip().rstrip("/")
    if prefix:
        return prefix
    user_id = project.beta_account_id or project.user_id or "anonymous"
    return f"users/{user_id}/projects/{project.project_id}/workspace"


def ensure_workspace_local(slug: str) -> Path:
    """Ensure ``STORAGE_ROOT/slug`` exists with property.json (download from R2 if needed)."""
    root = STORAGE_ROOT / slug
    meta_path = root / "property.json"
    if meta_path.exists():
        return root

    with _lock_for(slug):
        if meta_path.exists():
            return root

        if not r2_configured():
            raise FileNotFoundError(f"Workspace {slug} missing and R2 not configured")

        prefix = resolve_workspace_r2_prefix(slug)
        if not prefix:
            raise FileNotFoundError(f"No SaaS project linked to workspace {slug}")

        logger.info("Hydrating workspace %s from R2 prefix %s", slug, prefix)
        # Skip bulky finals/source — Studio plays them via R2 presign, not Railway /media.
        started = time.monotonic()
        count = download_prefix(prefix, root, skip_large_video=True)
        if count == 0 or not meta_path.exists():
            raise FileNotFoundError(
                f"Workspace {slug} not found under R2 prefix {prefix} (downloaded {count} files)"
            )
        _normalize_property_json(root)
        logger.info(
            "Hydrated workspace %s files=%s seconds=%.2f",
            slug,
            count,
            time.monotonic() - started,
        )
        return root
