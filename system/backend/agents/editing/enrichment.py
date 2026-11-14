"""Enrich timeline segments with narration text + audio paths.

Timeline Final pass historically left narration.audio_path empty.
Editing Agent must resolve audio from voice_execution / audio dir and
text from timeline_script — without modifying Timeline ownership of time.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _base_id(segment_id: str) -> str:
    """tl_002[seg_02_seg_03] → tl_002"""
    return segment_id.split("[", 1)[0].strip()


def enrich_timeline_narration(
    tl_segments: list[dict],
    timeline_script: dict[str, Any] | None = None,
    voice_execution: dict[str, Any] | None = None,
    audio_dir: str | Path | None = None,
) -> list[dict]:
    """Return shallow-copied segments with narration text/audio filled in."""

    text_by_id: dict[str, str] = {}
    if timeline_script:
        for ns in timeline_script.get("narration_segments", []):
            sid = str(ns.get("segment_id", ""))
            if sid:
                text_by_id[sid] = str(ns.get("text", ""))
                text_by_id[_base_id(sid)] = text_by_id[sid]

    audio_by_script: dict[str, dict] = {}
    if voice_execution:
        for vs in voice_execution.get("segments", []):
            script_id = str(vs.get("script_id", "") or vs.get("segment_id", ""))
            if script_id:
                audio_by_script[script_id] = vs
                audio_by_script[_base_id(script_id)] = vs

    audio_dir_path = Path(audio_dir) if audio_dir else None
    enriched: list[dict] = []

    for seg in tl_segments:
        seg = dict(seg)
        narr = dict(seg.get("narration") or {})
        sid = str(seg.get("id", ""))
        base = _base_id(sid)

        if not narr.get("text"):
            narr["text"] = text_by_id.get(sid) or text_by_id.get(base) or ""

        audio_meta = audio_by_script.get(sid) or audio_by_script.get(base)
        if audio_meta:
            path = str(audio_meta.get("audio_path", "") or "")
            if path and Path(path).exists():
                narr["audio_path"] = path
                narr["audio_duration"] = float(audio_meta.get("duration", 0) or 0)
            elif not narr.get("audio_path") and audio_dir_path:
                candidate = audio_dir_path / f"{base}.mp3"
                if candidate.exists():
                    narr["audio_path"] = str(candidate)

        if not narr.get("audio_path") and audio_dir_path:
            candidate = audio_dir_path / f"{base}.mp3"
            if candidate.exists():
                narr["audio_path"] = str(candidate)

        if narr.get("audio_path") and not narr.get("audio_duration"):
            try:
                from moviepy import AudioFileClip
                ac = AudioFileClip(narr["audio_path"])
                narr["audio_duration"] = round(float(ac.duration), 3)
                ac.close()
            except Exception:
                pass

        seg["narration"] = narr
        enriched.append(seg)

        if narr.get("audio_path"):
            logger.debug(
                "Enriched %s audio=%s text_len=%d",
                sid, Path(narr["audio_path"]).name, len(narr.get("text", "")),
            )
        else:
            logger.warning("No audio resolved for segment %s", sid)

    return enriched
