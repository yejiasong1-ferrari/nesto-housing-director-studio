"""Timeline Consistency Evaluator — 20% weight."""

from __future__ import annotations

from typing import Any

from backend.agents.evaluation.evaluators._helpers import clamp_score, safe_id
from backend.schemas.evaluation_schema import EvaluationIssue

DRIFT_TOLERANCE = 1.5  # seconds


class TimelineConsistencyEvaluator:
    weight = 0.20

    def evaluate(
        self,
        timeline: dict[str, Any],
        editing: dict[str, Any],
        render: dict[str, Any],
    ) -> tuple[float, list[EvaluationIssue]]:
        issues: list[EvaluationIssue] = []
        penalties = 0.0

        tl_segs = timeline.get("segments") or []
        edit_by = {
            safe_id(s.get("segment_id", "")): s
            for s in (editing.get("segments") or [])
        }
        render_by = {
            safe_id(s.get("segment_id", "")): s
            for s in (render.get("segments") or [])
        }

        planned_total = float(timeline.get("total_duration") or 0)
        rendered_total = float(render.get("duration") or 0)
        if planned_total > 0 and rendered_total > 0:
            drift = abs(rendered_total - planned_total)
            # Allow pad for narration finish / transition overlap
            if drift > 12.0:
                issues.append(EvaluationIssue(
                    type="timeline_drift",
                    segment_id="",
                    severity="low",
                    description=(
                        f"Rendered duration {rendered_total:.1f}s drifts from "
                        f"timeline plan {planned_total:.1f}s (Δ={drift:.1f}s)"
                    ),
                    evidence={"planned": planned_total, "rendered": rendered_total},
                    suggested_target="timeline",
                ))
                penalties += 6

        for tl in tl_segs:
            sid = safe_id(tl.get("id", ""))
            planned = float(
                tl.get("duration_decision", {}).get("editing_window")
                or tl.get("source", {}).get("video_duration")
                or 0
            )
            edit = edit_by.get(sid, {})
            edit_win = float(edit.get("editing_window") or 0)
            rend = render_by.get(sid, {})
            rend_dur = float(rend.get("duration") or 0)

            if planned > 0 and edit_win > 0 and abs(edit_win - planned) > DRIFT_TOLERANCE:
                issues.append(EvaluationIssue(
                    type="timeline_drift",
                    segment_id=sid,
                    severity="low",
                    description=(
                        f"Editing window {edit_win:.1f}s ≠ timeline plan {planned:.1f}s"
                    ),
                    evidence={"planned": planned, "editing_window": edit_win},
                    suggested_target="editing",
                ))
                penalties += 4

            if planned > 0 and rend_dur > 0 and abs(rend_dur - planned) > DRIFT_TOLERANCE + 0.5:
                issues.append(EvaluationIssue(
                    type="timeline_drift",
                    segment_id=sid,
                    severity="medium",
                    description=(
                        f"Rendered {rend_dur:.1f}s vs planned {planned:.1f}s for {sid}"
                    ),
                    evidence={"planned": planned, "rendered": rend_dur},
                    suggested_target="timeline",
                ))
                penalties += 6

            # Continuity: video_end of prev should roughly meet next video_start
        for i in range(len(tl_segs) - 1):
            a = tl_segs[i]
            b = tl_segs[i + 1]
            a_end = float(a.get("source", {}).get("video_end", 0) or 0)
            b_start = float(b.get("source", {}).get("video_start", 0) or 0)
            gap = b_start - a_end
            if gap > 2.0:
                issues.append(EvaluationIssue(
                    type="timeline_gap",
                    segment_id=safe_id(b.get("id", "")),
                    severity="low",
                    description=(
                        f"Source gap {gap:.1f}s between "
                        f"{safe_id(a.get('id',''))} and {safe_id(b.get('id',''))}"
                    ),
                    evidence={"gap": gap, "prev_end": a_end, "next_start": b_start},
                    suggested_target="timeline",
                ))
                penalties += 3

        return clamp_score(100.0 - penalties), issues
