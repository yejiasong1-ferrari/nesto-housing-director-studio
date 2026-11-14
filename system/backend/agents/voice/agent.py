"""Voice Agent — Temporal Voice Director.

Transforms time-aligned narration scripts into expressive voice
specifications with duration predictions for Timeline Optimization.

Voice Agent does NOT synthesize audio. Execution belongs to
VoiceExecutionService.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agents.voice.pipeline.duration_estimator import DurationEstimator
from backend.agents.voice.pipeline.emotional_alignment import EmotionalAlignment
from backend.agents.voice.pipeline.pronunciation import PronunciationController
from backend.agents.voice.pipeline.rhythm_planner import RhythmPlanner
from backend.agents.voice.pipeline.style_selector import StyleSelector
from backend.core.base_agent import BaseAgent
from backend.schemas.voice_schema import VoiceAgentOutput, VoicePlan, VoiceSegmentPlan
from backend.state.project_state import ProjectState

logger = logging.getLogger(__name__)

from backend.agents.script.speaking_rate import EN_WORDS_PER_SECOND

DEFAULT_BASE_WPS = EN_WORDS_PER_SECOND
DEFAULT_MISMATCH_THRESHOLD = 0.5


class VoiceAgent(BaseAgent):
    """Cinematic speech planning agent — reasoning only, no TTS."""

    agent_name = "voice"
    state_key = "voice"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        voice_cfg = self.config.get("voice", self.config)

        self.provider = str(voice_cfg.get("provider", "volcengine"))
        self.default_speaker = str(voice_cfg.get("default_speaker", ""))
        self.base_wps = float(voice_cfg.get("base_words_per_second", DEFAULT_BASE_WPS))
        self.mismatch_threshold = float(
            voice_cfg.get("duration_mismatch_threshold", DEFAULT_MISMATCH_THRESHOLD)
        )

        self.style_selector = StyleSelector()
        self.rhythm_planner = RhythmPlanner()
        self.duration_estimator = DurationEstimator(base_words_per_second=self.base_wps)
        self.pronunciation = PronunciationController()
        self.emotional_alignment = EmotionalAlignment()

    async def run(self, state: ProjectState) -> ProjectState:
        script_data = state.script or {}
        planning = state.planning or {}

        narration_segments = script_data.get("narration_segments") or script_data.get("segments", [])
        if not narration_segments:
            raise ValueError("Script output is required but narration_segments is empty")

        intent = planning.get("intent", {})
        script_style = script_data.get("style", {})
        meta = (state.user_goal.property_metadata if state.user_goal else None) or {}
        language = str(
            meta.get("narration_language")
            or script_style.get("language")
            or intent.get("narration_language")
            or "en"
        ).lower()

        logger.info(
            "Planning voice for %d segments | tone=%s | language=%s",
            len(narration_segments),
            intent.get("emotional_tone", ""),
            language,
        )

        profile = self.style_selector.select(
            intent=intent,
            script_style=script_style,
            provider=self.provider,
            default_voice_id=self.default_speaker,
            language=language,
        )

        segment_plans: list[VoiceSegmentPlan] = []
        for idx, seg in enumerate(narration_segments):
            seg_id = seg.get("segment_id") or seg.get("scene_id") or f"seg_{idx + 1:02d}"
            text = str(seg.get("text", "")).strip()
            scene_duration = float(seg.get("scene_duration") or (seg.get("end_time", 0) - seg.get("start_time", 0)))

            guide = self.pronunciation.analyze(text)
            tts_text = self.pronunciation.apply(text, guide)

            delivery = self.rhythm_planner.plan(seg, profile_emotion=profile.emotion)
            delivery = self.emotional_alignment.align(seg, delivery)
            delivery.emotion = str(seg.get("emotion", delivery.emotion))

            plan = VoiceSegmentPlan(
                id=f"voice_{idx + 1:03d}",
                script_id=seg_id,
                text=text,
                tts_text=tts_text,
                delivery=delivery,
                pronunciation=guide,
            )
            plan = self.duration_estimator.enrich_segment(
                plan,
                scene_duration=scene_duration,
                mismatch_threshold=self.mismatch_threshold,
                language=language,
            )
            segment_plans.append(plan)

        timeline_summary = self.duration_estimator.summarize(
            segment_plans,
            mismatch_threshold=self.mismatch_threshold,
        )

        voice_plan = VoicePlan(
            profile=profile,
            segments=segment_plans,
            timeline_summary=timeline_summary,
        )

        output = VoiceAgentOutput(
            project_id=state.project_id,
            voice_plan=voice_plan,
        )

        logger.info(
            "Voice plan complete: %d segments | voice=%.1fs scene=%.1fs delta=%+.1fs | over=%d under=%d",
            len(segment_plans),
            timeline_summary.total_estimated_voice_duration,
            timeline_summary.total_scene_duration,
            timeline_summary.total_duration_delta,
            len(timeline_summary.segments_over_budget),
            len(timeline_summary.segments_under_budget),
        )

        return self.write_state(state, output.model_dump(mode="json"))
