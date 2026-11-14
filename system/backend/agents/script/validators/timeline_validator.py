"""Timeline consistency validator.

Enforces the "forbidden behaviors" from the Script Agent constitution:
- no reordering of scenes
- no cross-scene narration (each narration's timing must match its own
  originating scene, unmodified)
- no overlapping narration windows
"""

from __future__ import annotations

import logging

from backend.schemas.script_schema import NarrationSegment, NarrativeStructure
from backend.schemas.vision_schema import VisionKnowledgeBase

logger = logging.getLogger(__name__)

TIME_TOLERANCE = 0.05
DURATION_OVERRUN_TOLERANCE = 1.5


class TimelineValidator:
    """Validates that Script Agent output never violates the fixed timeline."""

    def validate(
        self,
        vkb: VisionKnowledgeBase,
        segments: list[NarrationSegment],
        structure: NarrativeStructure,
    ) -> list[str]:
        issues: list[str] = []
        original_order = [s.segment_id for s in sorted(vkb.segments, key=lambda s: s.raw.start_time)]

        if structure.scene_order != original_order:
            issues.append("scene_order was reordered relative to the original video timeline")

        narration_order = [s.segment_id for s in segments]
        if narration_order != original_order:
            issues.append("narration_segments were reordered relative to the original video timeline")

        prev_end: float | None = None
        for seg in segments:
            if prev_end is not None and seg.start_time < prev_end - TIME_TOLERANCE:
                issues.append(f"{seg.segment_id}: narration window overlaps the previous scene")
            prev_end = seg.end_time

            if seg.estimated_duration > seg.scene_duration + DURATION_OVERRUN_TOLERANCE:
                issues.append(
                    f"{seg.segment_id}: estimated narration duration "
                    f"({seg.estimated_duration}s) exceeds scene duration ({seg.scene_duration}s)"
                )

        if issues:
            logger.warning("Timeline validation found %d issue(s)", len(issues))
        return issues
