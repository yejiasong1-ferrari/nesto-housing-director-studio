"""Module 6: Timeline Validator.

Checks the assembled timeline for three classes of issues:

1. Timing consistency
   - audio_duration <= editing_window for every segment (allow 0.5s buffer)

2. Duplicate narration
   - Consecutive segments that share key phrases get flagged.
     (e.g. "natural light", "hardwood floors" mentioned 3× in a row)

3. Must-show coverage
   - HERO segments from Planner hierarchy must appear in the final timeline.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from backend.schemas.timeline_schema import TimelineOutput, TimelineSegment, TimelineValidation

logger = logging.getLogger(__name__)

TIMING_BUFFER = 0.5   # seconds of allowed overshoot
DUPLICATE_WINDOW = 3  # check for repeats within this many consecutive segments
MIN_PHRASE_LEN = 3    # minimum word length of a "key phrase" worth deduplicating


class TimelineValidator:
    """Validate a completed TimelineOutput and return a TimelineValidation report."""

    def validate(
        self,
        output: TimelineOutput,
        hero_segment_ids: list[str] | None = None,
    ) -> TimelineValidation:
        issues: list[str] = []
        duplicate_warnings: list[str] = []

        # 1. Timing consistency
        for seg in output.segments:
            audio = seg.narration.audio_duration
            window = seg.duration_decision.editing_window
            if audio > window + TIMING_BUFFER:
                issues.append(
                    f"{seg.id}: audio={audio:.1f}s exceeds editing_window={window:.1f}s "
                    f"(delta={audio - window:.1f}s)"
                )

        # 2. Duplicate narration detection
        duplicate_warnings.extend(self._check_duplicates(output.segments))

        # 3. Must-show coverage
        timeline_source_ids: set[str] = set()
        for seg in output.segments:
            timeline_source_ids.update(seg.source_ids)

        must_show = hero_segment_ids or output.hero_segment_ids
        coverage: dict[str, bool] = {}
        for hid in must_show:
            present = hid in timeline_source_ids
            coverage[hid] = present
            if not present:
                issues.append(f"HERO segment {hid!r} is missing from the assembled timeline")

        is_valid = len(issues) == 0
        if duplicate_warnings:
            logger.warning("Timeline has %d duplicate narration warnings", len(duplicate_warnings))

        return TimelineValidation(
            is_valid=is_valid,
            issues=issues,
            must_show_coverage=coverage,
            duplicate_warnings=duplicate_warnings,
            total_duration_check=output.total_duration > 0,
        )

    def _check_duplicates(self, segments: list[TimelineSegment]) -> list[str]:
        warnings: list[str] = []
        phrase_window: list[set[str]] = []

        for seg in segments:
            phrases = self._extract_key_phrases(seg.narration.text)
            for prev_phrases in phrase_window:
                overlap = phrases & prev_phrases
                if overlap:
                    sample = ", ".join(sorted(overlap)[:2])
                    warnings.append(
                        f"{seg.id}: repeated phrase(s) near previous segment — [{sample}]"
                    )
            phrase_window.append(phrases)
            if len(phrase_window) > DUPLICATE_WINDOW:
                phrase_window.pop(0)

        return warnings

    def _extract_key_phrases(self, text: str) -> set[str]:
        """Return significant noun/adjective phrases (simple heuristic)."""
        words = re.findall(r"[a-z]+", text.lower())
        stop = {
            "a", "an", "the", "is", "are", "with", "and", "or", "of", "in", "on",
            "to", "for", "this", "that", "its", "it", "has", "have",
        }
        meaningful = [w for w in words if w not in stop and len(w) >= MIN_PHRASE_LEN]
        counter = Counter(meaningful)
        return {w for w, _ in counter.most_common(6)}
