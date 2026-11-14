"""Module 2: Attention Allocator — rule-only, hierarchical.

Computes raw attention scores, applies contrastive normalization,
assigns HERO/SUPPORT/TRANSITION roles, and builds hierarchy.
"""

from __future__ import annotations

import logging

from backend.agents.planner.attention.normalizer import contrastive_normalize
from backend.agents.planner.attention.role_assigner import build_hierarchy
from backend.agents.planner.attention.scoring import (
    DEFAULT_INTENT_GATE_THRESHOLD,
    DEFAULT_INTENT_PENALTY_MULTIPLIER,
    DEFAULT_WEIGHTS,
    build_attention_reasons,
    compute_aesthetic_score,
    compute_object_saliency,
    compute_vision_score,
    fuse_attention,
    match_intent_to_segment,
    narrative_importance_from_understanding,
)
from backend.schemas.planning_schema import (
    AttentionEntry,
    AttentionHierarchy,
    DirectorIntent,
    SegmentUnderstanding,
)
from backend.schemas.vision_schema import VisionKnowledgeBase

logger = logging.getLogger(__name__)


class AttentionAllocator:
    """Maps User Intent × Vision Segment → hierarchical attention map."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        gate_threshold: float = DEFAULT_INTENT_GATE_THRESHOLD,
        penalty_multiplier: float = DEFAULT_INTENT_PENALTY_MULTIPLIER,
        min_hero_segments: int = 2,
        hero_top_fraction: float = 0.15,
        transition_bottom_fraction: float = 0.30,
    ) -> None:
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.gate_threshold = gate_threshold
        self.penalty_multiplier = penalty_multiplier
        self.min_hero_segments = min_hero_segments
        self.hero_top_fraction = hero_top_fraction
        self.transition_bottom_fraction = transition_bottom_fraction

    def allocate(
        self,
        intent: DirectorIntent,
        vkb: VisionKnowledgeBase,
        segment_understanding: list[SegmentUnderstanding] | None = None,
    ) -> tuple[list[AttentionEntry], AttentionHierarchy]:
        """Produce contrastive-normalized attention map with roles and hierarchy."""
        understanding_by_id = {
            u.segment_id: u for u in (segment_understanding or [])
        }
        entries: list[AttentionEntry] = []

        for segment in vkb.segments:
            understanding = understanding_by_id.get(segment.segment_id)
            intent_match, intent_reasons = match_intent_to_segment(intent, segment)
            vision_score = compute_vision_score(segment, vkb)
            aesthetic_score = compute_aesthetic_score(segment)
            narrative_importance = narrative_importance_from_understanding(understanding)
            object_saliency, object_reasons = compute_object_saliency(intent, segment, vkb)

            score, signals = fuse_attention(
                intent_match,
                vision_score,
                narrative_importance,
                object_saliency,
                aesthetic_score=aesthetic_score,
                weights=self.weights,
                gate_threshold=self.gate_threshold,
                penalty_multiplier=self.penalty_multiplier,
            )

            reasons = build_attention_reasons(
                intent_match,
                vision_score,
                narrative_importance,
                intent_reasons,
                object_reasons,
                gate_threshold=self.gate_threshold,
            )

            entries.append(
                AttentionEntry(
                    segment_id=segment.segment_id,
                    score=score,
                    signals=signals,
                    reason=reasons,
                )
            )

        normalized = contrastive_normalize(
            entries,
            min_hero_segments=self.min_hero_segments,
            hero_top_fraction=self.hero_top_fraction,
            transition_bottom_fraction=self.transition_bottom_fraction,
        )
        hierarchy = build_hierarchy(normalized)

        logger.info(
            "Allocated hierarchical attention: %d HERO, %d SUPPORT, %d TRANSITION",
            len(hierarchy.hero_segments),
            len(hierarchy.support_segments),
            len(hierarchy.transition_segments),
        )
        return normalized, hierarchy
