"""Module 4: Timeline Alignment Engine — the critical constraint enforcer.

Guarantees narration never breaks the fixed video timeline:

    scene.start <= narration.start <= scene.end   (structurally always true,
    since narration is bound 1:1 to its scene and never repositioned)

The real work here is DURATION fit:

    IF narration too long   -> compress sentence (word-budget trim)
    IF narration too short  -> extend description (fact-based clause only)
    IF still invalid        -> flag needs_rewrite (never silently ship it)

Script Agent has "Temporal Authority" over narration content and pacing,
but NOT over timeline structure. It never shifts segment boundaries —
that decision belongs exclusively to the Timeline Optimization Agent.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agents.script.speaking_rate import (
    EN_WORDS_PER_MINUTE,
    count_units,
    estimated_duration as speak_estimated_duration,
    word_budget as speaking_word_budget,
)
from backend.agents.script.utils import clause_aware_trim, clause_aware_trim_zh
from backend.schemas.script_schema import NarrationSegment, NarrativeStructure, StyleConfig
from backend.schemas.vision_schema import VisionKnowledgeBase

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_COMPRESSED = "compressed"
STATUS_EXTENDED = "extended"
STATUS_NEEDS_REWRITE = "needs_rewrite"

MIN_SPEAKABLE_DURATION = 1.0  # seconds
DEFAULT_TOLERANCE = 0.25  # +/- 25% of word budget is acceptable without adjustment


class AlignmentEngine:
    """Fits compiled narration text to its scene's fixed duration."""

    def __init__(
        self,
        words_per_minute: float = EN_WORDS_PER_MINUTE,
        max_segment_words: int = 100,
        tolerance: float = DEFAULT_TOLERANCE,
    ) -> None:
        self.words_per_minute = words_per_minute
        self.max_segment_words = max_segment_words
        self.tolerance = tolerance

    def align(
        self,
        vkb: VisionKnowledgeBase,
        planning: dict[str, Any],
        structure: NarrativeStructure,
        styled_texts: dict[str, str],
        style: StyleConfig,
    ) -> list[NarrationSegment]:
        """Compile fitted NarrationSegment entries in fixed video order."""
        timeline_by_id = {
            str(t.get("segment_id", "")): t for t in planning.get("timeline_plan", [])
        }
        narrative_by_id = {
            str(n.get("segment_id", "")): n for n in planning.get("narrative_flow", [])
        }
        arc_by_id = dict(zip(structure.scene_order, structure.story_arc))

        segments_out: list[NarrationSegment] = []
        for seg in sorted(vkb.segments, key=lambda s: s.raw.start_time):
            seg_id = seg.segment_id
            tl = timeline_by_id.get(seg_id, {})
            start = float(tl.get("start", seg.raw.start_time))
            end = float(tl.get("end", seg.raw.end_time))
            duration = max(end - start, 0.01)
            role = str(tl.get("role", "SUPPORT")) or "SUPPORT"

            text = styled_texts.get(seg_id, "")
            lang = (style.language or "en").lower()
            text, status, notes = self._fit_duration(text, duration, role, seg, language=lang)

            word_count = count_units(text, lang)
            estimated_duration = speak_estimated_duration(text, lang)
            rate = (word_count / estimated_duration) if estimated_duration > 0 else 1.0
            information_density = round(
                min(1.0, (word_count / duration) / rate) if duration > 0 else 0.0, 3
            )
            narrative = narrative_by_id.get(seg_id, {})

            segments_out.append(
                NarrationSegment(
                    segment_id=seg_id,
                    scene_id=seg_id,
                    start_time=start,
                    end_time=end,
                    text=text,
                    arc_stage=arc_by_id.get(seg_id, "explore"),
                    role=role,
                    emotion=str(narrative.get("emotion", "neutral")) or "neutral",
                    voice_style=f"{style.energy}_{style.tone}"[:60],
                    information_density=information_density,
                    importance=float(tl.get("importance", 0.5)),
                    word_count=word_count,
                    estimated_duration=estimated_duration,
                    scene_duration=round(duration, 2),
                    alignment_status=status,
                    alignment_notes=notes,
                    room_type=seg.knowledge.room_type,
                    tone=style.tone,
                )
            )

        n_issues = sum(1 for s in segments_out if s.alignment_status != STATUS_OK)
        logger.info(
            "Alignment Engine fitted %d segments (%d adjusted/flagged)",
            len(segments_out),
            n_issues,
        )
        return segments_out

    def _fit_duration(
        self,
        text: str,
        duration: float,
        role: str,
        segment: Any,
        language: str = "en",
    ) -> tuple[str, str, list[str]]:
        notes: list[str] = []
        status = STATUS_OK

        if duration < MIN_SPEAKABLE_DURATION:
            return text, STATUS_NEEDS_REWRITE, ["scene_too_short_for_narration"]

        if (language or "en").lower() == "zh":
            return self._fit_duration_zh(text, duration, role, segment)

        word_budget = speaking_word_budget(
            duration, "en", min_units=1, max_units=self.max_segment_words
        )
        words = text.split()

        if role == "TRANSITION":
            # No narration emphasis: cap tightly, never extend.
            if len(words) > word_budget:
                text = clause_aware_trim(text, word_budget)
                status = STATUS_COMPRESSED
                notes.append("transition_capped")
            return text, status, notes

        lower_bound = max(1, round(word_budget * (1 - self.tolerance)))
        upper_bound = max(lower_bound + 1, round(word_budget * (1 + self.tolerance)))

        if len(words) > upper_bound:
            text = clause_aware_trim(text, upper_bound)
            status = STATUS_COMPRESSED
            notes.append(f"trimmed_to_{upper_bound}_words")
        elif len(words) < lower_bound:
            extension = self._extension_clause(segment, language="en")
            if extension:
                text = text.rstrip(". ") + f", {extension}."
                status = STATUS_EXTENDED
                notes.append("appended_fact_based_clause")
            words = text.split()
            if len(words) < max(1, round(word_budget * 0.4)):
                status = STATUS_NEEDS_REWRITE
                notes.append("insufficient_visible_content_for_duration")

        return text, status, notes

    def _fit_duration_zh(
        self,
        text: str,
        duration: float,
        role: str,
        segment: Any,
    ) -> tuple[str, str, list[str]]:
        """Fit Chinese narration by character budget (not space-delimited words)."""
        notes: list[str] = []
        status = STATUS_OK
        # Measured Volcengine zh TTS ≈ 4.2 chars/sec — 5.0 was too generous
        # and let sentences outrun 2–5s shots.
        char_budget = speaking_word_budget(duration, "zh", min_units=18, max_units=90)
        chars = len(text.replace(" ", ""))

        if role == "TRANSITION":
            # Still keep a marketing minimum (feature + brief benefit)
            trans_budget = max(28, min(char_budget, round(char_budget * 0.95)))
            if chars > trans_budget:
                text = clause_aware_trim_zh(text, trans_budget)
                status = STATUS_COMPRESSED
                notes.append("transition_capped_zh")
            return text, status, notes

        lower_bound = max(22, round(char_budget * (1 - self.tolerance)))
        upper_bound = max(lower_bound + 1, round(char_budget * (1 + self.tolerance)))

        if chars > upper_bound:
            text = clause_aware_trim_zh(text, upper_bound)
            status = STATUS_COMPRESSED
            notes.append(f"trimmed_to_{upper_bound}_chars_zh")
        elif chars < lower_bound:
            extension = self._extension_clause(segment, language="zh")
            if extension:
                base = text.rstrip("。.! ")
                text = f"{base}，{extension}。"
                status = STATUS_EXTENDED
                notes.append("appended_fact_based_clause_zh")
            chars = len(text.replace(" ", ""))
            if chars < max(16, round(char_budget * 0.35)):
                status = STATUS_NEEDS_REWRITE
                notes.append("insufficient_visible_content_for_duration")

        return text, status, notes

    def _extension_clause(self, segment: Any, language: str = "en") -> str:
        """Extend narration using only additional facts already present in the VKB."""
        remaining_points = list(segment.knowledge.selling_points[1:2] or [])
        furniture = list(segment.knowledge.furniture[:1] or [])
        appliances = list(segment.knowledge.appliances[:1] or [])
        candidates = [str(x) for x in (remaining_points + furniture + appliances) if x]

        if (language or "en").lower() == "zh":
            # Never append English Vision labels into Chinese narration.
            cjk_facts = [c for c in candidates if self._cjk_ratio(c) >= 0.35]
            if not cjk_facts:
                return ""
            return f"并配备{cjk_facts[0]}，提升日常使用便利"

        if remaining_points:
            return f"complete with {remaining_points[0].lower()}"
        if furniture:
            return f"complete with {furniture[0].lower()}"
        if appliances:
            return f"including {appliances[0].lower()}"
        return ""

    @staticmethod
    def _cjk_ratio(text: str) -> float:
        if not text:
            return 0.0
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        return cjk / max(len(text), 1)