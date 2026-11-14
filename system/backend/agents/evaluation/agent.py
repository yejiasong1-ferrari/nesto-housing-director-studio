"""Evaluation Agent — single final-review pass.

Compares Timeline + Script + Voice + Editing + Render metadata,
produces one structured feedback. Does not re-enter after fixes.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agents.evaluation.critic.llm_critic import LLMCritic
from backend.agents.evaluation.evaluators.audio_balance import AudioBalanceEvaluator
from backend.agents.evaluation.evaluators.audio_visual import AudioVisualEvaluator
from backend.agents.evaluation.evaluators.cinematic import CinematicEvaluator
from backend.agents.evaluation.evaluators.subtitle import SubtitleEvaluator
from backend.agents.evaluation.evaluators.technical import TechnicalEvaluator
from backend.agents.evaluation.evaluators.timeline import TimelineConsistencyEvaluator
from backend.agents.evaluation.feedback.generator import FeedbackGenerator
from backend.core.base_agent import BaseAgent
from backend.schemas.evaluation_schema import CategoryScores, EvaluationResult
from backend.state.project_state import ProjectState

logger = logging.getLogger(__name__)


class EvaluationAgent(BaseAgent):
    """Final quality controller — one evaluation, one feedback package."""

    agent_name = "evaluation"
    state_key = "evaluation"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_provider: Any | None = None,
    ) -> None:
        super().__init__(config)
        self.llm_provider = llm_provider
        self.av = AudioVisualEvaluator()
        self.sub = SubtitleEvaluator()
        self.tl = TimelineConsistencyEvaluator()
        self.cin = CinematicEvaluator()
        self.tech = TechnicalEvaluator()
        self.balance = AudioBalanceEvaluator()
        self.critic = LLMCritic(llm_provider)
        self.generator = FeedbackGenerator()

    async def run(self, state: ProjectState) -> ProjectState:
        timeline = state.timeline or {}
        script = state.script or {}
        voice = state.voice or {}
        editing = state.editing or {}
        render = state.render or {}
        vision = state.vision or {}
        planning = state.planning or {}
        audio_config = state.audio_config

        if not timeline.get("segments"):
            raise ValueError("Evaluation requires timeline segments")
        if not render:
            logger.warning("Evaluation running without render metadata")

        logger.info(
            "Evaluation Agent: %d tl segs | render=%s | llm=%s",
            len(timeline.get("segments", [])),
            render.get("status", "n/a"),
            self.critic.available,
        )

        av_score, av_issues = self.av.evaluate(
            timeline, script, editing, vision, planning, voice,
        )
        sub_score, sub_issues = self.sub.evaluate(editing, script)
        tl_score, tl_issues = self.tl.evaluate(timeline, editing, render)
        cin_score, cin_issues = self.cin.evaluate(timeline, editing, planning)
        tech_score, tech_issues = self.tech.evaluate(render, timeline, editing)
        bal_score, bal_issues = self.balance.evaluate(audio_config, render)
        # Fold audio-balance into technical (10% bucket)
        tech_score = round((tech_score * 0.7) + (bal_score * 0.3), 1)

        all_issues = (
            av_issues + sub_issues + tl_issues + cin_issues + tech_issues + bal_issues
        )
        scores = CategoryScores(
            audiovisual=av_score,
            subtitle=sub_score,
            timeline=tl_score,
            cinematic=cin_score,
            technical=tech_score,
        )

        # Compact context for LLM critic
        context = {
            "hero_segments": planning.get("hierarchy", {}).get("hero_segments", []),
            "segment_rooms": [
                {
                    "id": s.get("id"),
                    "room": s.get("room_type"),
                    "role": s.get("role"),
                    "video_start": s.get("source", {}).get("video_start"),
                    "video_end": s.get("source", {}).get("video_end"),
                    "text": (s.get("narration") or {}).get("text", "")[:100],
                }
                for s in (timeline.get("segments") or [])[:12]
            ],
            "render_duration": render.get("duration"),
            "timeline_duration": timeline.get("total_duration"),
        }

        fixes = await self.critic.critique(all_issues, context)
        result = self.generator.build(
            project_id=state.project_id,
            scores=scores,
            issues=all_issues,
            fixes=fixes,
            llm_used=self.critic.available,
        )

        logger.info(
            "Evaluation: %s | issues=%d fixes=%d approved=%s",
            result.summary,
            len(result.issues),
            len(result.priority_fixes),
            result.approved,
        )
        for fix in result.priority_fixes:
            logger.info(
                "  %s → %s [%s] %s",
                fix.id, fix.target_agent, fix.action.type, fix.problem[:80],
            )

        return self.write_state(state, result.model_dump(mode="json"))
