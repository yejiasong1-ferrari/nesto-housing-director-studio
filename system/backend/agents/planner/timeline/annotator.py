"""Module 5: Timeline Annotator — rule-only assembler.

Mounts hierarchical semantic layers onto fixed temporal structure.
Never reorders or adjusts timestamps.
"""

from __future__ import annotations

import logging

from backend.agents.planner.attention.normalizer import ROLE_TRANSITION
from backend.schemas.planning_schema import (
    AttentionEntry,
    CameraNotes,
    CinematicStrategy,
    NarrativeEntry,
    TimelinePlanEntry,
)
from backend.schemas.vision_schema import VisionKnowledgeBase

logger = logging.getLogger(__name__)

MAX_TRANSITION_NARRATION = 0.20


class TimelineAnnotator:
    """Assembles timeline plan from attention, narrative, and cinematic layers."""

    def annotate(
        self,
        vkb: VisionKnowledgeBase,
        attention_map: list[AttentionEntry],
        narrative_flow: list[NarrativeEntry],
        cinematic_strategy: list[CinematicStrategy],
    ) -> list[TimelinePlanEntry]:
        """Produce timeline plan preserving original segment order and timestamps."""
        attention_by_id = {a.segment_id: a for a in attention_map}
        narrative_by_id = {n.segment_id: n for n in narrative_flow}
        cinematic_by_id = {c.segment_id: c for c in cinematic_strategy}

        segments = sorted(vkb.segments, key=lambda s: s.raw.start_time)
        plan: list[TimelinePlanEntry] = []

        for segment in segments:
            seg_id = segment.segment_id
            attention = attention_by_id.get(seg_id)
            narrative = narrative_by_id.get(seg_id)
            cinematic = cinematic_by_id.get(seg_id)

            role = attention.role if attention else (narrative.role if narrative else "")
            importance = attention.score if attention else 0.5
            narration_weight = narrative.narration_weight if narrative else 0.5
            if role == ROLE_TRANSITION:
                narration_weight = min(narration_weight, MAX_TRANSITION_NARRATION)

            execution_hints = cinematic.execution_hints if cinematic else ["standard_pace"]
            camera_emphasis = cinematic.camera_language if cinematic else "standard coverage"

            cinematic_notes = {}
            if cinematic:
                cinematic_notes = {
                    "camera_language": cinematic.camera_language,
                    "attention_guidance": cinematic.attention_guidance,
                    "emotion_engine": cinematic.emotion_engine,
                }

            plan.append(
                TimelinePlanEntry(
                    segment_id=seg_id,
                    start=segment.raw.start_time,
                    end=segment.raw.end_time,
                    importance=importance,
                    role=role,
                    editing_strategy=execution_hints,
                    narration_weight=narration_weight,
                    camera_notes=CameraNotes(emphasis=camera_emphasis),
                    cinematic_notes=cinematic_notes,
                    narrative_role=narrative.role if narrative else role,
                    cinematic_intent=cinematic.editing_intent if cinematic else "",
                )
            )

        logger.info("Assembled timeline with %d entries (order preserved)", len(plan))
        return plan
