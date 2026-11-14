"""Revision Engine — apply one human edit to on-disk artifacts.

Deterministic file patching only. No LLM. Consulted by the orchestrator,
which sequences the actual Agent/Service calls the dependency graph says
are required (voice re-synthesis, rendering).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


def _save(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def patch_script_text(ws, segment_id: str, new_text: str) -> dict[str, Any]:
    """Human-authored narration text replaces the segment's text everywhere.

    No LLM rewrite — the user is the author here. Returns a summary of what
    changed so the caller (orchestrator) knows to re-synthesize voice.
    """
    new_text = new_text.strip()
    if not new_text:
        raise ValueError("Narration text cannot be empty")

    changed: dict[str, Any] = {"segment_id": segment_id, "old_text": "", "new_text": new_text}

    editing = _load(ws.editing_plan_path)
    for seg in editing.get("segments") or []:
        if seg.get("segment_id") == segment_id:
            changed["old_text"] = seg.get("narration_text", "")
            seg["narration_text"] = new_text
            break
    _save(ws.editing_plan_path, editing)

    timeline = _load(ws.timeline_output_path)
    for seg in timeline.get("segments") or []:
        if seg.get("id") == segment_id:
            seg.setdefault("narration", {})["text"] = new_text
            break
    _save(ws.timeline_output_path, timeline)

    for path in (ws.timeline_script_path, ws.script_output_path):
        script = _load(path)
        found = False
        for seg in script.get("narration_segments") or []:
            if seg.get("segment_id") == segment_id:
                seg["text"] = new_text
                found = True
                break
        if found:
            _save(path, script)

    return changed


def patch_audio_paths(ws, segment_id: str, audio_path: str, audio_duration: float) -> None:
    """After re-synthesis, point editing/timeline at the new audio file."""
    # Prefer a path under this workspace so export on another host can remap by basename.
    p = Path(audio_path) if audio_path else None
    if p and p.exists():
        dest = ws.audio_dir / p.name
        if p.resolve() != dest.resolve():
            import shutil

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        audio_path = str(dest.resolve())

    editing = _load(ws.editing_plan_path)
    for seg in editing.get("segments") or []:
        if seg.get("segment_id") == segment_id:
            seg["audio_path"] = audio_path
            seg["audio_duration"] = round(audio_duration, 2)
            break
    _save(ws.editing_plan_path, editing)

    timeline = _load(ws.timeline_output_path)
    for seg in timeline.get("segments") or []:
        if seg.get("id") == segment_id:
            seg.setdefault("narration", {})["audio_path"] = audio_path
            seg.setdefault("narration", {})["audio_duration"] = round(audio_duration, 2)
            break
    _save(ws.timeline_output_path, timeline)


def patch_audio_offset(ws, segment_id: str, offset_seconds: float) -> float:
    """Clamp and persist a per-segment narration start nudge (seconds)."""
    offset_seconds = max(0.0, min(float(offset_seconds), 8.0))

    editing = _load(ws.editing_plan_path)
    applied = 0.0
    for seg in editing.get("segments") or []:
        if seg.get("segment_id") == segment_id:
            seg["audio_offset"] = offset_seconds
            applied = offset_seconds
            break
    _save(ws.editing_plan_path, editing)
    return applied


def read_segment(ws, segment_id: str) -> dict[str, Any]:
    editing = _load(ws.editing_plan_path)
    for seg in editing.get("segments") or []:
        if seg.get("segment_id") == segment_id:
            return seg
    raise KeyError(f"Segment {segment_id!r} not found in editing plan")
