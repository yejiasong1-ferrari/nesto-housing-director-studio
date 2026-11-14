"""Module 1: Timeline Analyzer.

Synthesises Vision + Planner + Script + Voice into a single list of
EnrichedSegments. This is the only module that touches raw agent outputs;
all downstream modules receive EnrichedSegment objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.agents.vision.modules.room_onset import relative_audio_offset, resolve_visible_end

logger = logging.getLogger(__name__)


@dataclass
class EnrichedSegment:
    """Unified representation of one scene, ready for Timeline reasoning."""

    segment_id: str
    room_type: str
    semantic_meaning: str

    # VKB / script timing
    video_start: float
    video_end: float
    video_duration: float

    # Planner hierarchy
    role: str        # HERO | SUPPORT | TRANSITION
    importance: float
    arc_stage: str
    narrative_function: str
    emotion: str
    narration_weight: float

    # Script narration
    narration_text: str
    tts_text: str

    # Voice (prefer execution; fallback to plan estimate)
    audio_duration: float    # actual measured duration
    estimated_duration: float
    audio_path: str
    delivery_speed: float
    voice_emotion: str

    # Visual
    focus_elements: list[str] = field(default_factory=list)

    # Primary-room onset (absolute seconds) → narration delay inside the shot
    room_visible_start: float = 0.0
    room_visible_end: float = 0.0
    audio_offset: float = 0.0
    room_stage: str = ""


class TimelineAnalyzer:
    """Merge all agent outputs into a list of EnrichedSegments (order-preserving)."""

    def analyze(
        self,
        vkb: dict[str, Any],
        planning: dict[str, Any],
        script: dict[str, Any],
        voice_plan: dict[str, Any],
        voice_execution: dict[str, Any],
    ) -> list[EnrichedSegment]:
        vkb_segs = {s["segment_id"]: s for s in vkb.get("segments", [])}
        attn = {a["segment_id"]: a for a in planning.get("attention_map", [])}
        narr_flow = {n["segment_id"]: n for n in planning.get("narrative_flow", [])}
        seg_understanding = {u["segment_id"]: u for u in planning.get("segment_understanding", [])}
        emphasis_targets = [str(t) for t in (planning.get("emphasis_targets") or [])]

        script_segs = {s["segment_id"]: s for s in script.get("narration_segments", [])}

        voice_plan_segs: dict[str, dict] = {}
        for vs in voice_plan.get("voice_plan", voice_plan).get("segments", []):
            voice_plan_segs[vs["script_id"]] = vs

        voice_exec_segs: dict[str, dict] = {}
        for ve in voice_execution.get("segments", []):
            voice_exec_segs[ve["script_id"]] = ve

        scene_order: list[str] = script.get("narrative_structure", {}).get("scene_order", [])
        if not scene_order:
            scene_order = sorted(vkb_segs.keys())

        enriched: list[EnrichedSegment] = []
        for seg_id in scene_order:
            vkb_seg = vkb_segs.get(seg_id, {})
            raw = vkb_seg.get("raw", {})
            knowledge = vkb_seg.get("knowledge", {})

            script_seg = script_segs.get(seg_id, {})
            attn_entry = attn.get(seg_id, {})
            narr_entry = narr_flow.get(seg_id, {})
            understand = seg_understanding.get(seg_id, {})

            vp = voice_plan_segs.get(seg_id, {})
            ve = voice_exec_segs.get(seg_id, {})

            video_start = raw.get("start_time", script_seg.get("start_time", 0.0))
            video_end = raw.get("end_time", script_seg.get("end_time", 0.0))
            video_dur = raw.get("duration", video_end - video_start)
            visible_start = float(vkb_seg.get("room_visible_start") or 0.0)
            visible_end = resolve_visible_end(
                float(video_start), float(video_end), float(vkb_seg.get("room_visible_end") or 0.0)
            )
            audio_offset = relative_audio_offset(
                float(video_start), float(video_end), visible_start
            )
            room_label = knowledge.get("room_type", script_seg.get("room_type", ""))

            actual_dur = float(ve.get("duration", 0.0))
            voice_estimated = float(vp.get("estimated_duration", 0.0))
            # Deepest fallback: Script Agent's word-count estimate (available even
            # on first Timeline pass before Voice has run).
            script_estimated = float(script_seg.get("estimated_duration", 0.0))
            audio_dur = actual_dur if actual_dur > 0 else (
                voice_estimated if voice_estimated > 0 else script_estimated
            )
            estimated_dur = voice_estimated if voice_estimated > 0 else script_estimated

            delivery = vp.get("delivery", {})

            selling_points = knowledge.get("selling_points", [])
            furniture = knowledge.get("furniture", [])
            appliances = knowledge.get("appliances", [])
            base_focus = (selling_points[:3] + furniture[:1] + appliances[:1])
            # Presence-gated director emphasis leads the visual focus order so
            # the requested object is zoomed/held — only if it exists here.
            if emphasis_targets:
                from backend.workflows.emphasis import matched_facts
                emphasis_here = matched_facts(emphasis_targets, knowledge)
                focus = list(dict.fromkeys(emphasis_here + base_focus))[:5]
            else:
                focus = base_focus

            enriched.append(
                EnrichedSegment(
                    segment_id=seg_id,
                    room_type=room_label,
                    semantic_meaning=understand.get("semantic_meaning", ""),
                    video_start=float(video_start),
                    video_end=float(video_end),
                    video_duration=float(video_dur),
                    role=attn_entry.get("role", script_seg.get("role", "SUPPORT")),
                    importance=float(attn_entry.get("score", script_seg.get("importance", 0.5))),
                    arc_stage=script_seg.get("arc_stage", "explore"),
                    narrative_function=narr_entry.get("narrative_function", ""),
                    emotion=narr_entry.get("emotion", script_seg.get("emotion", "neutral")),
                    narration_weight=float(narr_entry.get("narration_weight", 0.5)),
                    narration_text=script_seg.get("text", vp.get("text", "")),
                    tts_text=vp.get("tts_text", script_seg.get("text", "")),
                    audio_duration=audio_dur,
                    estimated_duration=estimated_dur,
                    audio_path=ve.get("audio_path", ""),
                    delivery_speed=float(delivery.get("speed", 1.0)),
                    voice_emotion=delivery.get("emotion", "neutral"),
                    focus_elements=focus,
                    room_visible_start=visible_start if visible_start > 0 else float(video_start),
                    room_visible_end=visible_end,
                    audio_offset=audio_offset,
                    room_stage=str(vkb_seg.get("room_stage") or ""),
                )
            )

        logger.info("Analyzer: %d enriched segments from %d VKB segments", len(enriched), len(vkb_segs))
        return enriched
