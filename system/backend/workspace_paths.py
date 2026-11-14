"""Rewrite host-specific absolute media paths to the local workspace."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_local_audio_path(root: Path, audio_path: str) -> str:
    """Map an audio_path (often absolute from another host) onto ``root/audio/<name>``."""
    raw = (audio_path or "").strip()
    if not raw:
        return ""
    p = Path(raw)
    if p.is_file():
        return str(p.resolve())

    audio_dir = root / "audio"
    candidates = [
        audio_dir / p.name,
        root / raw,
        root / "audio" / raw,
    ]
    # …/audio/tl_001.mp3 embedded in a foreign absolute path
    parts = p.parts
    if "audio" in parts:
        idx = parts.index("audio")
        candidates.append(root.joinpath(*parts[idx:]))

    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    return raw


def to_portable_audio_path(root: Path, audio_path: str) -> str:
    """Prefer workspace-relative ``audio/<file>.mp3`` so any host can resolve it."""
    local = resolve_local_audio_path(root, audio_path)
    if not local:
        return ""
    path = Path(local)
    if not path.is_file():
        return audio_path
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        dest = root / "audio" / path.name
        if path.resolve() != dest.resolve():
            import shutil

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        return f"audio/{path.name}"


def rewrite_workspace_media_paths(root: Path) -> int:
    """Fix ``audio_path`` fields to portable ``audio/<file>.mp3`` relative paths.

    Studio edits on Railway write absolute ``/app/storage/...`` paths; Mac Worker
    downloads the same files under ``storage/properties/<slug>/``. Portable
    relative paths survive host switches; call ``materialize_workspace_audio_paths``
    immediately before MoviePy render.
    """
    return _transform_workspace_audio_paths(root, portable=True)


def materialize_workspace_audio_paths(root: Path) -> int:
    """Expand audio_path fields to absolute local files for rendering."""
    return _transform_workspace_audio_paths(root, portable=False)


def _transform_workspace_audio_paths(root: Path, *, portable: bool) -> int:
    root = Path(root)
    if not root.is_dir():
        return 0

    def rewrite_fields(obj: object) -> int:
        changed = 0
        if isinstance(obj, dict):
            if "audio_path" in obj and isinstance(obj["audio_path"], str):
                if portable:
                    new = to_portable_audio_path(root, obj["audio_path"])
                else:
                    local = resolve_local_audio_path(root, obj["audio_path"])
                    new = str(Path(local).resolve()) if local and Path(local).is_file() else obj["audio_path"]
                if new and new != obj["audio_path"]:
                    obj["audio_path"] = new
                    changed += 1
            for value in obj.values():
                changed += rewrite_fields(value)
        elif isinstance(obj, list):
            for item in obj:
                changed += rewrite_fields(item)
        return changed

    total = 0
    targets = [
        root / "editing" / "editing_plan.json",
        root / "timeline" / "timeline_output.json",
        root / "timeline" / "timeline_script.json",
        root / "voice" / "voice_execution.json",
        root / "script" / "script_output.json",
    ]
    for path in targets:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("skip path rewrite for %s: %s", path, exc)
            continue
        n = rewrite_fields(data)
        if n:
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            total += n
    if total:
        logger.info(
            "%s %s audio_path field(s) under %s",
            "Portable-rewrote" if portable else "Materialized",
            total,
            root,
        )
    return total
