"""Structural validator for the Temporal Narration Graph.

Enforces the "forced behaviors" from the Script Agent constitution:
- every narration must bind to exactly one segment_id / scene_id
- every narration must carry start_time / end_time
- every narration must be directly TTS-consumable (non-empty text,
  except TRANSITION scenes which may carry a minimal connective phrase)
"""

from __future__ import annotations

import logging

from backend.agents.script.pipeline.alignment_engine import STATUS_NEEDS_REWRITE
from backend.schemas.script_schema import NarrationSegment

logger = logging.getLogger(__name__)


class SchemaValidator:
    """Validates structural correctness of compiled narration segments."""

    def validate(self, segments: list[NarrationSegment]) -> list[str]:
        issues: list[str] = []
        seen_ids: set[str] = set()

        for seg in segments:
            if not seg.segment_id:
                issues.append("narration segment missing segment_id")
                continue

            if seg.segment_id in seen_ids:
                issues.append(f"{seg.segment_id}: duplicate narration segment (must be 1 scene -> 1 narration)")
            seen_ids.add(seg.segment_id)

            if seg.scene_id != seg.segment_id:
                issues.append(f"{seg.segment_id}: scene_id must equal segment_id")

            if seg.end_time <= seg.start_time:
                issues.append(f"{seg.segment_id}: missing/invalid start_time-end_time binding")

            if not seg.text.strip() and seg.role != "TRANSITION":
                issues.append(f"{seg.segment_id}: empty narration text is not TTS-ready")

            if seg.alignment_status == STATUS_NEEDS_REWRITE:
                issues.append(f"{seg.segment_id}: flagged needs_rewrite — {'; '.join(seg.alignment_notes)}")

        if issues:
            logger.warning("Schema validation found %d issue(s)", len(issues))
        return issues
