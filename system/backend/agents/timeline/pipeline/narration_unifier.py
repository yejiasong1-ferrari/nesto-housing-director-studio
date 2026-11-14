"""Narration Unifier — re-narrate merged timeline segments.

After the Timeline Agent merges adjacent scenes into one editorial segment,
this module produces a single unified narration sentence for each merged
group so Voice Agent can synthesize one clean audio file per timeline
segment.

For non-merged (single-source) segments the original narration is used
unchanged.

For merged segments:
  1. LLM re-narration (preferred) — coherent sentence covering the
     combined selling points.
  2. Fallback — use the head segment's original narration if LLM fails.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.agents.script.speaking_rate import (
    speakable_window,
    word_budget as speaking_word_budget,
)
from backend.agents.script.pipeline.marketing_enricher import sanitize_timeline_narration

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "prompts" / "timeline" / "merge_narration.md"
)

# Target ~85% of the editing window so speech nearly fills the merged shot
# (no long silent walkthrough tail) while leaving breathing room.
WINDOW_FILL_RATIO = 0.85


def _load_prompt(**kwargs: str) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(**kwargs)


class NarrationUnifier:
    """Produce timeline-segment-level narration from approved timeline output."""

    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    async def unify(
        self,
        timeline: dict[str, Any],
        script: dict[str, Any],
        vkb: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return a list of narration dicts keyed by timeline segment id.

        Each item is compatible with the Voice Agent's narration_segments input:
          segment_id, text, arc_stage, role, emotion, scene_duration,
          start_time, end_time, importance, room_type
        """
        tl_segments = timeline.get("segments", [])
        script_by_id = {
            s["segment_id"]: s
            for s in script.get("narration_segments", [])
        }
        vkb_by_id = {s["segment_id"]: s for s in vkb.get("segments", [])}
        style = script.get("style", {})

        merged_tasks: list[dict] = []
        result_map: dict[str, str] = {}

        for tl_seg in tl_segments:
            source_ids: list[str] = tl_seg.get("source_ids", [])

            safe_id = tl_seg["id"].split("[")[0]

            if len(source_ids) == 1:
                # Non-merged — just carry the original text
                orig = script_by_id.get(source_ids[0], {})
                result_map[safe_id] = orig.get("text", tl_seg.get("narration", {}).get("text", ""))
                continue

            # Merged segment — needs re-narration
            editing_window = tl_seg.get("duration_decision", {}).get("editing_window", 0)
            lang = (style.get("language") or "en").lower()
            speak_window = speakable_window(
                editing_window,
                tl_seg.get("source", {}).get("video_duration") or 0,
            )
            word_budget = speaking_word_budget(
                speak_window,
                lang,
                fill_ratio=WINDOW_FILL_RATIO,
                min_units=16 if lang == "zh" else 8,
            )

            focus_elements: list[str] = tl_seg.get("visual_plan", {}).get("focus_elements", [])
            if not focus_elements:
                for sid in source_ids:
                    vkb_seg = vkb_by_id.get(sid, {})
                    focus_elements.extend(vkb_seg.get("knowledge", {}).get("selling_points", [])[:2])

            original_narrations = [
                script_by_id.get(sid, {}).get("text", "")
                for sid in source_ids
                if script_by_id.get(sid, {}).get("text", "")
            ]

            merged_tasks.append({
                "timeline_segment_id": safe_id,
                "room_type": tl_seg.get("room_type", ""),
                "role": tl_seg.get("role", "SUPPORT"),
                "arc_stage": tl_seg.get("arc_stage", "explore"),
                "story_phase": tl_seg.get("visual_plan", {}).get("story_phase", ""),
                "focus_elements": focus_elements[:5],
                "video_duration_seconds": round(speak_window, 1),
                "word_budget": word_budget,
                "original_narrations": original_narrations,
            })

        # LLM re-narration for merged groups
        if merged_tasks and self.llm_provider is not None:
            llm_results = await self._llm_renarrate(merged_tasks, style)
            result_map.update(llm_results)

        # Fallback: use result_map keyed by safe_id already;
        # fill in any merged group LLM didn't cover
        for task in merged_tasks:
            tid = task["timeline_segment_id"]   # already safe_id
            if tid not in result_map:
                # Use first original narration as fallback
                fallback = task["original_narrations"][0] if task["original_narrations"] else ""
                result_map[tid] = fallback
                logger.warning("NarrationUnifier fallback for %s: using first source narration", tid)

        # Build unified narration segment list aligned to timeline order
        unified: list[dict[str, Any]] = []
        for tl_seg in tl_segments:
            tid = tl_seg["id"]
            # Use a filename-safe id: strip "[seg_xx_seg_yy...]" bracket suffix
            safe_id = tid.split("[")[0]
            source_ids = tl_seg.get("source_ids", [])
            head_script = script_by_id.get(source_ids[0], {}) if source_ids else {}
            narr = tl_seg.get("narration", {})
            dur_dec = tl_seg.get("duration_decision", {})

            # result_map is keyed by safe_id (never the bracketed timeline id)
            unified_text = (
                result_map.get(safe_id)
                or narr.get("text")
                or head_script.get("text")
                or ""
            )
            lang = (style.get("language") or "zh").strip().lower()
            unified_text = sanitize_timeline_narration(
                unified_text,
                room_type=str(tl_seg.get("room_type") or head_script.get("room_type") or ""),
                language=lang,
            )
            editing_window = dur_dec.get("editing_window", tl_seg.get("source", {}).get("video_duration", 0))

            unified.append({
                "segment_id": safe_id,
                "scene_id": safe_id,
                "text": unified_text,
                "arc_stage": tl_seg.get("arc_stage", head_script.get("arc_stage", "explore")),
                "role": tl_seg.get("role", head_script.get("role", "SUPPORT")),
                "emotion": narr.get("emotion", head_script.get("emotion", "neutral")),
                "room_type": tl_seg.get("room_type", head_script.get("room_type", "")),
                "importance": tl_seg.get("importance", head_script.get("importance", 0.5)),
                "scene_duration": editing_window,
                "start_time": tl_seg.get("timeline_start", 0.0),
                "end_time": tl_seg.get("timeline_end", 0.0),
                "source_ids": source_ids,
                "story_phase": tl_seg.get("visual_plan", {}).get("story_phase", ""),
                "is_merged": len(source_ids) > 1,
            })

        merged_count = len(merged_tasks)
        llm_count = sum(
            1 for t in merged_tasks
            if result_map.get(t["timeline_segment_id"], "") not in (
                t["original_narrations"][0] if t["original_narrations"] else "", ""
            )
        )
        logger.info(
            "NarrationUnifier: %d timeline segments | %d merged groups | %d LLM re-narrated",
            len(unified), merged_count, llm_count,
        )
        return unified

    async def _llm_renarrate(
        self, tasks: list[dict], style: dict
    ) -> dict[str, str]:
        from backend.services.llm.base import LLMMessage
        from backend.agents.script.utils import SCRIPT_LLM_MAX_TOKENS, safe_extract_json

        prompt = _load_prompt(
            style_json=json.dumps(style, indent=2),
            segments_json=json.dumps(tasks, indent=2),
        )
        try:
            response = await self.llm_provider.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.35,
                max_tokens=SCRIPT_LLM_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning("LLM re-narration failed (%s) — using fallback", exc)
            return {}

        if not response.content or not response.content.strip():
            logger.warning("LLM re-narration returned empty content — using fallback")
            return {}

        data = safe_extract_json(response.content, fallback=[])
        results: dict[str, str] = {}
        items = data if isinstance(data, list) else []
        for item in items:
            if isinstance(item, dict) and item.get("timeline_segment_id") and item.get("text"):
                results[str(item["timeline_segment_id"])] = str(item["text"]).strip()

        logger.info("LLM re-narration: %d/%d merged groups renarrated", len(results), len(tasks))
        return results
