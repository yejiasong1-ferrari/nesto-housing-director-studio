"""Editing Strategy Agent — cinematic reasoning → abstract visual strategies.

Architecture (cursor.md / architecture.md):
  CinematicReasoner (LLM ~20%) → rule planners (~80%) → ConstraintValidator

Does NOT: cut video, change times, merge/delete segments, rewrite narration,
or call FFmpeg/MoviePy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.agents.editing.director.cinematic_reasoner import CinematicReasoner
from backend.agents.editing.enrichment import enrich_timeline_narration
from backend.agents.editing.planners.audio_strategy import AudioStrategyPlanner
from backend.agents.editing.planners.pacing_strategy import PacingStrategyPlanner
from backend.agents.editing.planners.subtitle_strategy import SubtitleStrategyPlanner
from backend.agents.editing.planners.transition_strategy import TransitionStrategyPlanner
from backend.agents.editing.planners.visual_strategy import VisualStrategyPlanner
from backend.agents.editing.validators.editing_constraint import EditingConstraintValidator
from backend.core.base_agent import BaseAgent
from backend.schemas.editing_schema import EditingPlan, EditingSegmentPlan
from backend.state.project_state import ProjectState

logger = logging.getLogger(__name__)


class EditingAgent(BaseAgent):
    """Bridge between Timeline (narrative structure) and Rendering (execution)."""

    agent_name = "editing"
    state_key = "editing"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_provider: Any | None = None,
        audio_dir: str | Path | None = None,
    ) -> None:
        super().__init__(config)
        self.llm_provider = llm_provider
        self.audio_dir = Path(audio_dir) if audio_dir else None
        self.reasoner = CinematicReasoner(llm_provider)
        self.visual_planner = VisualStrategyPlanner()
        self.pacing_planner = PacingStrategyPlanner()
        self.transition_planner = TransitionStrategyPlanner(
            continuous_walkthrough=bool(
                (config or {}).get("continuous_walkthrough", True)
            )
        )
        self.subtitle_planner = SubtitleStrategyPlanner()
        self.audio_planner = AudioStrategyPlanner()
        self.validator = EditingConstraintValidator()

    async def run(self, state: ProjectState) -> ProjectState:
        timeline = state.timeline or {}
        planning = state.planning or {}
        script = state.script or {}
        voice = state.voice or {}

        tl_segments = timeline.get("segments", [])
        if not tl_segments:
            raise ValueError("Timeline output is required but segments is empty")

        timeline_script = script if script.get("narration_segments") else None
        voice_exec = voice if voice.get("segments") else None
        tl_segments = enrich_timeline_narration(
            tl_segments,
            timeline_script=timeline_script,
            voice_execution=voice_exec,
            audio_dir=self.audio_dir,
        )

        intent = planning.get("intent", {})
        style = str(intent.get("emotional_tone", "warm_modern_luxury"))
        audience = str(intent.get("target_audience", ""))

        vision_by_id = self._index_vision(state.vision or {})

        if self.llm_provider is None or not self.reasoner.llm_available:
            raise RuntimeError(
                "Editing Agent requires an LLM provider. "
                "Start the LLM server — rule fallback is disabled."
            )

        logger.info(
            "Editing Agent: %d segments | style=%s | llm=%s",
            len(tl_segments), style, self.reasoner.llm_available,
        )

        decisions = await self.reasoner.reason(
            tl_segments, style, audience, vision_by_id=vision_by_id,
        )

        segment_plans: list[EditingSegmentPlan] = []
        prev_room = ""
        for tl_seg in tl_segments:
            sid = tl_seg.get("id", "")
            decision = decisions[sid]
            plan = self._plan_segment(tl_seg, decision, prev_room)
            plan = self.validator.validate_segment(plan)
            segment_plans.append(plan)
            prev_room = tl_seg.get("room_type", "") or prev_room

        editing_plan = EditingPlan(
            project_id=state.project_id,
            style=style,
            target_audience=audience,
            llm_used=self.reasoner.llm_available,
            segments=segment_plans,
        )

        logger.info(
            "Editing plan: %d segments | ops=%s",
            len(segment_plans),
            [s.primary_strategy().type for s in segment_plans],
        )
        return self.write_state(state, editing_plan.model_dump(mode="json"))

    def _plan_segment(
        self,
        tl_seg: dict,
        decision,
        prev_room: str,
    ) -> EditingSegmentPlan:
        narr = tl_seg.get("narration", {})
        dur_dec = tl_seg.get("duration_decision", {})
        source = tl_seg.get("source", {})
        narration_text = str(narr.get("text", ""))

        visual = self.visual_planner.plan(decision, tl_seg)
        pacing = self.pacing_planner.plan(tl_seg, decision)
        transition = self.transition_planner.plan(tl_seg, decision, prev_room)
        subtitle = self.subtitle_planner.plan(tl_seg, decision, narration_text)
        audio = self.audio_planner.plan(tl_seg, decision)

        plan = EditingSegmentPlan(
            segment_id=tl_seg.get("id", ""),
            source_ids=tl_seg.get("source_ids", []),
            room_type=tl_seg.get("room_type", ""),
            role=tl_seg.get("role", "SUPPORT"),
            director_decision=decision,
            visual_strategy=visual,
            pacing=pacing,
            transition=transition,
            subtitle=subtitle,
            audio=audio,
            narration_text=narration_text,
            audio_path=str(narr.get("audio_path", "")),
            audio_duration=float(narr.get("audio_duration", 0) or 0),
            editing_window=float(dur_dec.get("editing_window", 0) or 0),
            video_start=float(source.get("video_start", 0) or 0),
            video_end=float(source.get("video_end", 0) or 0),
            video_duration=float(source.get("video_duration", 0) or 0),
            timeline_start=float(tl_seg.get("timeline_start", 0) or 0),
            timeline_end=float(tl_seg.get("timeline_end", 0) or 0),
            audio_offset=max(0.0, float(tl_seg.get("audio_offset", 0) or 0)),
        )
        plan.sync_legacy_fields()
        return plan

    def _index_vision(self, vision: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for key in ("segments", "rooms", "scene_segments"):
            for item in vision.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                sid = str(item.get("id") or item.get("segment_id") or "")
                if sid:
                    out[sid] = {
                        "room": item.get("room_type") or item.get("room", ""),
                        "objects": item.get("objects") or item.get("detected_objects") or [],
                        "attributes": item.get("attributes") or {},
                    }
        return out


# Backward-compat alias
EditingStrategyAgent = EditingAgent
