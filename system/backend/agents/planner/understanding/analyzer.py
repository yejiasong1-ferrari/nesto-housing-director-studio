"""Step 2: Segment Understanding — rule-only semantic analysis.

For each VKB segment, compute:
- semantic_meaning: room + top selling point + intent alignment
- visual_strength: vision quality score
- narrative_potential: room sellability × intent match × selling density
"""

from __future__ import annotations

import logging

from backend.agents.planner.attention.scoring import compute_vision_score, match_intent_to_segment
from backend.schemas.planning_schema import DirectorIntent, SegmentUnderstanding
from backend.schemas.vision_schema import VKBSegment, VisionKnowledgeBase

logger = logging.getLogger(__name__)

ROOM_NARRATIVE_WEIGHTS: dict[str, float] = {
    "kitchen": 0.95,
    "studio": 0.90,
    "living": 0.85,
    "bedroom": 0.80,
    "bathroom": 0.55,
    "dining": 0.70,
    "balcony": 0.65,
    "exterior": 0.60,
    "entry": 0.45,
    "hallway": 0.30,
    "closet": 0.35,
    "storage": 0.30,
    "utility": 0.25,
}


def _room_narrative_weight(room_type: str) -> float:
    room_lower = room_type.lower()
    if "mixed" in room_lower:
        return 0.82
    for key, weight in ROOM_NARRATIVE_WEIGHTS.items():
        if key in room_lower:
            return weight
    return 0.50


def _intent_alignment_label(intent_match: float, matched_tags: list[str]) -> str:
    if intent_match >= 0.75:
        return "strong_intent_alignment"
    if intent_match >= 0.45:
        return "moderate_intent_alignment"
    if matched_tags:
        return "partial_intent_alignment"
    return "neutral_coverage"


def _build_semantic_meaning(
    segment: VKBSegment,
    intent_match: float,
    matched_tags: list[str],
) -> str:
    room = segment.knowledge.room_type or "space"
    top_point = segment.knowledge.selling_points[0] if segment.knowledge.selling_points else ""
    alignment = _intent_alignment_label(intent_match, matched_tags)

    parts = [f"primary_{room.lower().replace(' ', '_')}_showcase"]
    if top_point:
        parts.append(top_point.lower().replace(" ", "_")[:40])
    parts.append(alignment)
    return " | ".join(parts)


def _compute_narrative_potential(
    segment: VKBSegment,
    intent_match: float,
) -> float:
    room_weight = _room_narrative_weight(segment.knowledge.room_type)
    selling_density = min(len(segment.knowledge.selling_points) / 5.0, 1.0)
    score = room_weight * (0.5 + intent_match * 0.5) * (0.6 + selling_density * 0.4)
    return round(min(1.0, score), 3)


class SegmentUnderstandingAnalyzer:
    """Analyzes semantic meaning and narrative potential per segment."""

    def analyze(
        self,
        intent: DirectorIntent,
        vkb: VisionKnowledgeBase,
    ) -> list[SegmentUnderstanding]:
        """Produce segment understanding for all VKB segments (video order)."""
        segments = sorted(vkb.segments, key=lambda s: s.raw.start_time)
        results: list[SegmentUnderstanding] = []

        for segment in segments:
            intent_match, matched_tags = match_intent_to_segment(intent, segment)
            visual_strength = compute_vision_score(segment, vkb)
            narrative_potential = _compute_narrative_potential(segment, intent_match)
            semantic_meaning = _build_semantic_meaning(segment, intent_match, matched_tags)

            results.append(
                SegmentUnderstanding(
                    segment_id=segment.segment_id,
                    semantic_meaning=semantic_meaning,
                    visual_strength=visual_strength,
                    narrative_potential=narrative_potential,
                )
            )

        logger.info("Analyzed understanding for %d segments", len(results))
        return results
