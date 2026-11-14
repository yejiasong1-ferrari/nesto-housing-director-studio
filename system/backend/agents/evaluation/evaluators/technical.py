"""Technical Evaluator — 10% weight (deterministic, no LLM)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agents.evaluation.evaluators._helpers import clamp_score, safe_id
from backend.schemas.evaluation_schema import EvaluationIssue


class TechnicalEvaluator:
    weight = 0.10

    def evaluate(
        self,
        render: dict[str, Any],
        timeline: dict[str, Any],
        editing: dict[str, Any],
    ) -> tuple[float, list[EvaluationIssue]]:
        issues: list[EvaluationIssue] = []
        penalties = 0.0

        status = render.get("status", "")
        if status and status != "success":
            issues.append(EvaluationIssue(
                type="encoding",
                segment_id="",
                severity="high",
                description=f"Render status is '{status}': {render.get('error', '')}",
                evidence={"status": status},
                suggested_target="rendering",
            ))
            penalties += 40

        out = render.get("output_path", "")
        if out and not Path(out).exists():
            issues.append(EvaluationIssue(
                type="encoding",
                segment_id="",
                severity="high",
                description="Final video file missing",
                evidence={"path": out},
                suggested_target="rendering",
            ))
            penalties += 40

        fps = float(render.get("fps") or 0)
        if fps and abs(fps - 30.0) > 0.5:
            issues.append(EvaluationIssue(
                type="encoding",
                segment_id="",
                severity="low",
                description=f"Unexpected fps {fps}",
                evidence={"fps": fps},
                suggested_target="rendering",
            ))
            penalties += 5

        # Canvas size is fixed by RenderService (1080×1920 or 1920×1080).
        # Do not inspect width/height here — it cannot improve quality and
        # previously forced a wasted second encode on every portrait video.

        # Per-segment audio missing
        for seg in editing.get("segments") or []:
            sid = safe_id(seg.get("segment_id", ""))
            text = (seg.get("narration_text") or "").strip()
            path = (seg.get("audio_path") or "").strip()
            if text and (not path or not Path(path).exists()):
                issues.append(EvaluationIssue(
                    type="audio_clipping",
                    segment_id=sid,
                    severity="high",
                    description=f"Missing narration audio for {sid}",
                    evidence={"audio_path": path},
                    suggested_target="voice",
                ))
                penalties += 8

        for rseg in render.get("segments") or []:
            if rseg.get("audio_mixed") is False and (rseg.get("duration") or 0) > 1:
                # Only flag if editing had narration
                sid = safe_id(rseg.get("segment_id", ""))
                issues.append(EvaluationIssue(
                    type="audio_clipping",
                    segment_id=sid,
                    severity="medium",
                    description=f"Render reports audio_mixed=false for {sid}",
                    evidence={},
                    suggested_target="rendering",
                ))
                penalties += 5

        return clamp_score(100.0 - penalties), issues
