"""Subtitle Alignment Evaluator — 15% weight."""

from __future__ import annotations

from typing import Any

from backend.agents.evaluation.evaluators._helpers import clamp_score, safe_id
from backend.schemas.evaluation_schema import EvaluationIssue

MAX_CHARS = 110
MAX_WORDS = 28


class SubtitleEvaluator:
    weight = 0.15

    def evaluate(
        self,
        editing: dict[str, Any],
        script: dict[str, Any],
    ) -> tuple[float, list[EvaluationIssue]]:
        issues: list[EvaluationIssue] = []
        penalties = 0.0

        segs = editing.get("segments") or []
        if not segs:
            # Fall back to script texts
            segs = [
                {
                    "segment_id": s.get("segment_id"),
                    "narration_text": s.get("text", ""),
                    "subtitle": {"enabled": True},
                }
                for s in (script.get("narration_segments") or [])
            ]

        for seg in segs:
            sid = safe_id(seg.get("segment_id", ""))
            text = (seg.get("narration_text") or "").strip()
            sub = seg.get("subtitle") or {}
            enabled = bool(sub.get("enabled", True)) if isinstance(sub, dict) else True

            if not text:
                continue

            if enabled and len(text) > MAX_CHARS:
                issues.append(EvaluationIssue(
                    type="subtitle_overflow",
                    segment_id=sid,
                    severity="medium",
                    description=f"Subtitle text too long ({len(text)} chars)",
                    evidence={"chars": len(text), "text": text[:80]},
                    suggested_target="script",
                ))
                penalties += 8

            words = text.split()
            if len(words) > MAX_WORDS:
                issues.append(EvaluationIssue(
                    type="subtitle_overflow",
                    segment_id=sid,
                    severity="low",
                    description=f"Narration/subtitle wordy ({len(words)} words)",
                    evidence={"words": len(words)},
                    suggested_target="script",
                ))
                penalties += 5

            # Missing subtitle when narration exists
            if text and not enabled:
                issues.append(EvaluationIssue(
                    type="subtitle_missing",
                    segment_id=sid,
                    severity="low",
                    description="Narration present but subtitle disabled",
                    evidence={},
                    suggested_target="editing",
                ))
                penalties += 4

        return clamp_score(100.0 - penalties), issues
