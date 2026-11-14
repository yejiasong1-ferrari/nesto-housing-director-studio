"""Capability 3: Duration Prediction.

Predicts narration duration for Timeline Optimization Agent.
"""

from __future__ import annotations

import re

from backend.agents.script.speaking_rate import EN_WORDS_PER_SECOND, count_units, estimated_duration
from backend.schemas.voice_schema import TimelineConstraintSummary, VoiceSegmentPlan

WORD_RE = re.compile(r"[A-Za-z0-9']+")


class DurationEstimator:
    """Estimate speech duration from text, speed, and pauses."""

    def __init__(self, base_words_per_second: float = EN_WORDS_PER_SECOND) -> None:
        self.base_words_per_second = base_words_per_second

    def count_words(self, text: str) -> int:
        return len(WORD_RE.findall(text))

    def estimate_segment(
        self,
        text: str,
        delivery_speed: float,
        pause_before: float,
        pause_after: float,
        language: str = "en",
    ) -> tuple[float, int, float]:
        units = count_units(text, language)
        base = estimated_duration(text, language)
        speed = max(float(delivery_speed or 1.0), 0.5)
        speech_duration = (base / speed) if base else 0.0
        speech_rate = (units / speech_duration) if speech_duration > 0 else self.base_words_per_second
        total = pause_before + speech_duration + pause_after
        return round(total, 2), units, round(speech_rate, 2)

    def enrich_segment(
        self,
        plan: VoiceSegmentPlan,
        scene_duration: float,
        mismatch_threshold: float = 0.5,
        language: str = "en",
    ) -> VoiceSegmentPlan:
        duration, words, rate = self.estimate_segment(
            plan.tts_text or plan.text,
            plan.delivery.speed,
            plan.delivery.pause_before,
            plan.delivery.pause_after,
            language=language,
        )
        delta = round(duration - scene_duration, 2)
        plan.estimated_duration = duration
        plan.estimated_words = words
        plan.speech_rate = rate
        plan.scene_duration = scene_duration
        plan.duration_delta = delta
        plan.needs_timeline_adjustment = abs(delta) > mismatch_threshold
        return plan

    def summarize(
        self,
        segments: list[VoiceSegmentPlan],
        mismatch_threshold: float = 0.5,
    ) -> TimelineConstraintSummary:
        total_scene = sum(s.scene_duration for s in segments)
        total_voice = sum(s.estimated_duration for s in segments)
        over = [s.script_id for s in segments if s.duration_delta > mismatch_threshold]
        under = [s.script_id for s in segments if s.duration_delta < -mismatch_threshold]
        return TimelineConstraintSummary(
            total_scene_duration=round(total_scene, 2),
            total_estimated_voice_duration=round(total_voice, 2),
            total_duration_delta=round(total_voice - total_scene, 2),
            segments_over_budget=over,
            segments_under_budget=under,
        )
