"""Planner Agent — hierarchical attention-conditioned director.

Pipeline:
1. Intent Interpreter           [LLM]
2. Segment Understanding        [Rule]
3. Attention Allocator          [Rule + normalize + roles]
4. Narrative Flow Builder       [LLM, uses hierarchy]
5. Cinematic Reasoner           [Rule primary, LLM notes optional]
6. Timeline Annotator           [Rule]
7. Quality Validator            [Rule]
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agents.planner.attention.allocator import AttentionAllocator
from backend.agents.planner.attention.scoring import (
    DEFAULT_INTENT_GATE_THRESHOLD,
    DEFAULT_INTENT_PENALTY_MULTIPLIER,
    DEFAULT_WEIGHTS,
)
from backend.agents.planner.cinematic.reasoner import CinematicReasoner
from backend.agents.planner.intent.interpreter import IntentInterpreter
from backend.agents.planner.narrative.flow_builder import NarrativeFlowBuilder
from backend.agents.planner.narrative.space_selection import apply_space_narration_selection
from backend.agents.planner.quality.validator import QualityValidator
from backend.agents.planner.timeline.annotator import TimelineAnnotator
from backend.agents.planner.understanding.analyzer import SegmentUnderstandingAnalyzer
from backend.core.base_agent import BaseAgent
from backend.schemas.planning_schema import (
    NarrativeEntry,
    PlannerOutput,
    SegmentReasoning,
)
from backend.schemas.vision_schema import VisionKnowledgeBase
from backend.state.project_state import ProjectState

logger = logging.getLogger(__name__)


def _build_segment_reasoning(
    narrative_flow: list[NarrativeEntry],
) -> list[SegmentReasoning]:
    """Backward-compat shim for downstream agents expecting segment_reasoning."""
    role_map = {
        "HERO": "hero_segment",
        "SUPPORT": "support_segment",
        "TRANSITION": "transition_segment",
    }
    return [
        SegmentReasoning(
            segment_id=n.segment_id,
            role=role_map.get(n.role, n.role),
            focus_points=[n.narrative_function] if n.narrative_function else [],
            narration_weight=n.narration_weight,
        )
        for n in narrative_flow
    ]


class PlannerAgent(BaseAgent):
    """Hierarchical attention-conditioned cinematic planner."""

    agent_name = "planner"
    state_key = "planning"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_provider: Any | None = None,
    ) -> None:
        super().__init__(config)
        self.llm_provider = llm_provider

        planner_cfg = self.config.get("planner", self.config)
        weights = planner_cfg.get("attention_weights", DEFAULT_WEIGHTS)
        gate_threshold = planner_cfg.get("intent_gate_threshold", DEFAULT_INTENT_GATE_THRESHOLD)
        penalty_multiplier = planner_cfg.get(
            "intent_penalty_multiplier", DEFAULT_INTENT_PENALTY_MULTIPLIER
        )
        hierarchy_cfg = planner_cfg.get("hierarchy", {})

        self.intent_interpreter = IntentInterpreter(llm_provider)
        self.segment_analyzer = SegmentUnderstandingAnalyzer()
        self.attention_allocator = AttentionAllocator(
            weights=weights,
            gate_threshold=gate_threshold,
            penalty_multiplier=penalty_multiplier,
            min_hero_segments=hierarchy_cfg.get("min_hero_segments", 2),
            hero_top_fraction=hierarchy_cfg.get("hero_top_fraction", 0.15),
            transition_bottom_fraction=hierarchy_cfg.get("transition_bottom_fraction", 0.30),
        )
        self.narrative_builder = NarrativeFlowBuilder(llm_provider)
        self.cinematic_reasoner = CinematicReasoner(llm_provider)
        self.timeline_annotator = TimelineAnnotator()
        self.quality_validator = QualityValidator(
            min_hero_segments=hierarchy_cfg.get("min_hero_segments", 2),
            min_transition_fraction=hierarchy_cfg.get("transition_bottom_fraction", 0.30),
        )

    async def run(self, state: ProjectState) -> ProjectState:
        """Execute the hierarchical planner pipeline."""
        user_prompt = state.user_goal.prompt
        property_metadata = state.user_goal.property_metadata

        vkb = self._load_vkb(state)
        logger.info(
            "Planning for %d segments | prompt: %s",
            len(vkb.segments),
            user_prompt[:80] if user_prompt else "(empty)",
        )

        # Step 1: Intent [LLM]
        logger.info("Step 1: Intent Interpreter")
        intent = await self.intent_interpreter.interpret(user_prompt, property_metadata)
        logger.info(
            "  goal=%s | primary=%s | tags=%s | tone=%s",
            intent.goal,
            intent.intent_graph.primary,
            intent.intent_tags,
            intent.emotional_tone,
        )

        # Step 2: Segment Understanding [Rule]
        logger.info("Step 2: Segment Understanding")
        segment_understanding = self.segment_analyzer.analyze(intent, vkb)

        # Step 3: Attention + Hierarchy [Rule]
        logger.info("Step 3: Attention Allocator (contrastive normalization)")
        attention_map, hierarchy = self.attention_allocator.allocate(
            intent, vkb, segment_understanding
        )
        for entry in attention_map[:3]:
            logger.info(
                "  %s: score=%.2f role=%s (I=%.2f V=%.2f N=%.2f O=%.2f) %s",
                entry.segment_id,
                entry.score,
                entry.role,
                entry.signals.intent_match,
                entry.signals.vision,
                entry.signals.narrative_importance,
                entry.signals.object_saliency,
                entry.reason[:4],
            )
        logger.info(
            "  hierarchy: HERO=%s | TRANSITION=%s",
            hierarchy.hero_segments[:5],
            hierarchy.transition_segments[:5],
        )

        # Step 4: Narrative [LLM]
        logger.info("Step 4: Narrative Flow Builder")
        narrative_flow = await self.narrative_builder.build(intent, vkb, attention_map)
        narrative_flow = apply_space_narration_selection(vkb, narrative_flow)
        heroes = [n for n in narrative_flow if n.role == "HERO"]
        logger.info("  %d HERO entries, %d narrative entries", len(heroes), len(narrative_flow))

        # Step 5: Cinematic [Rule primary]
        logger.info("Step 5: Cinematic Reasoner (role-based)")
        cinematic_strategy = await self.cinematic_reasoner.reason(
            intent, vkb, attention_map, narrative_flow
        )
        intents = {c.editing_intent for c in cinematic_strategy}
        logger.info("  editing intents: %s", intents)

        # Step 6: Timeline [Rule]
        logger.info("Step 6: Timeline Annotator")
        timeline_plan = self.timeline_annotator.annotate(
            vkb, attention_map, narrative_flow, cinematic_strategy
        )
        logger.info("  Assembled %d timeline entries (order preserved)", len(timeline_plan))

        output = PlannerOutput(
            project_id=state.project_id,
            agent_name=self.agent_name,
            intent=intent,
            segment_understanding=segment_understanding,
            attention_map=attention_map,
            hierarchy=hierarchy,
            narrative_flow=narrative_flow,
            cinematic_strategy=cinematic_strategy,
            timeline_plan=timeline_plan,
            segment_reasoning=_build_segment_reasoning(narrative_flow),
        )

        # Step 7: Quality validation [Rule]
        logger.info("Step 7: Quality Validator")
        self.quality_validator.validate(output)

        # Director emphasis: derive concrete targets from the ORIGINAL user brief
        # (kept even when intake expanded a short prompt to the default). Presence
        # gating happens downstream — Planner only records what the user asked for.
        from backend.workflows.emphasis import parse_emphasis_targets
        original_brief = ""
        if isinstance(property_metadata, dict):
            original_brief = str(property_metadata.get("intent_original") or "")
        emphasis_targets = parse_emphasis_targets(original_brief)
        if emphasis_targets:
            logger.info("  director emphasis targets: %s", emphasis_targets)

        data = output.model_dump()
        data["emphasis_targets"] = emphasis_targets
        return self.write_state(state, data)

    def _load_vkb(self, state: ProjectState) -> VisionKnowledgeBase:
        vision_data = state.vision or {}
        if not vision_data:
            raise ValueError("Vision Knowledge Base is required but state.vision is empty")
        from backend.agents.vision.modules.space_evidence_validator import validate_verified_vkb
        from backend.workflows.room_naming import normalize_room_names

        vkb = validate_verified_vkb(VisionKnowledgeBase(**vision_data))
        vkb = normalize_room_names(vkb)
        state.vision = vkb.model_dump()
        return vkb
