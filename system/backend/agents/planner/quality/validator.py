"""Quality validator for hierarchical planner output.

Logs warnings/errors when quality rules are violated.
"""

from __future__ import annotations

import logging

from backend.schemas.planning_schema import (
    AttentionEntry,
    AttentionHierarchy,
    CinematicStrategy,
    PlannerOutput,
)

logger = logging.getLogger(__name__)

MIN_HERO_SEGMENTS = 2
MIN_TRANSITION_FRACTION = 0.30
MIN_SCORE_RANGE = 0.50


class QualityValidator:
    """Validates hierarchical planner output against director quality rules."""

    def __init__(
        self,
        min_hero_segments: int = MIN_HERO_SEGMENTS,
        min_transition_fraction: float = MIN_TRANSITION_FRACTION,
        min_score_range: float = MIN_SCORE_RANGE,
    ) -> None:
        self.min_hero_segments = min_hero_segments
        self.min_transition_fraction = min_transition_fraction
        self.min_score_range = min_score_range

    def validate(self, output: PlannerOutput) -> list[str]:
        """Validate output and return list of violation messages."""
        violations: list[str] = []

        violations.extend(self._check_hierarchy(output.hierarchy, len(output.attention_map)))
        violations.extend(self._check_score_contrast(output.attention_map))
        violations.extend(self._check_strategy_variety(output.cinematic_strategy))

        for msg in violations:
            logger.error("Quality violation: %s", msg)

        if not violations:
            logger.info("Quality validation passed")

        return violations

    def _check_hierarchy(self, hierarchy: AttentionHierarchy, total: int) -> list[str]:
        violations: list[str] = []
        if len(hierarchy.hero_segments) < self.min_hero_segments:
            violations.append(
                f"Need >= {self.min_hero_segments} HERO segments, got {len(hierarchy.hero_segments)}"
            )
        if total > 0:
            transition_frac = len(hierarchy.transition_segments) / total
            if transition_frac < self.min_transition_fraction:
                violations.append(
                    f"Need >= {self.min_transition_fraction:.0%} TRANSITION segments, "
                    f"got {transition_frac:.0%} ({len(hierarchy.transition_segments)}/{total})"
                )
        return violations

    def _check_score_contrast(self, attention_map: list[AttentionEntry]) -> list[str]:
        if len(attention_map) < 2:
            return []
        scores = [e.score for e in attention_map]
        score_range = max(scores) - min(scores)
        if score_range < self.min_score_range:
            return [f"Score range {score_range:.2f} < minimum {self.min_score_range}"]
        return []

    def _check_strategy_variety(self, strategies: list[CinematicStrategy]) -> list[str]:
        if len(strategies) < 2:
            return []
        hint_sets = [tuple(s.execution_hints) for s in strategies]
        if len(set(hint_sets)) == 1:
            return ["All segments have identical execution_hints"]
        return []
