"""Feedback generator — assemble single EvaluationResult."""

from __future__ import annotations

from backend.agents.evaluation.evaluators._helpers import clamp_score
from backend.schemas.evaluation_schema import (
    CategoryScores,
    EvaluationIssue,
    EvaluationResult,
    PriorityFix,
)

# Weights from design
W_AV = 0.40
W_SUB = 0.15
W_TL = 0.20
W_CIN = 0.15
W_TECH = 0.10

APPROVE_THRESHOLD = 88.0
MAX_FIXES = 6


class FeedbackGenerator:
    def build(
        self,
        project_id: str,
        scores: CategoryScores,
        issues: list[EvaluationIssue],
        fixes: list[PriorityFix],
        llm_used: bool,
    ) -> EvaluationResult:
        overall = clamp_score(
            scores.audiovisual * W_AV
            + scores.subtitle * W_SUB
            + scores.timeline * W_TL
            + scores.cinematic * W_CIN
            + scores.technical * W_TECH
        )

        # Prioritize high severity, then medium; cap count for single pass
        severity_rank = {"high": 0, "medium": 1, "low": 2}
        ranked = sorted(
            fixes,
            key=lambda f: (severity_rank.get(f.severity, 9), f.id),
        )
        # Deduplicate by (segment, action.type)
        seen: set[tuple[str, str]] = set()
        priority: list[PriorityFix] = []
        for fix in ranked:
            key = (fix.segment, fix.action.type)
            if key in seen:
                continue
            seen.add(key)
            priority.append(fix)
            if len(priority) >= MAX_FIXES:
                break

        approved = overall >= APPROVE_THRESHOLD and not any(
            i.severity == "high" for i in issues
        )

        summary_parts = [
            f"overall={overall:.0f}",
            f"AV={scores.audiovisual:.0f}",
            f"sub={scores.subtitle:.0f}",
            f"tl={scores.timeline:.0f}",
            f"cin={scores.cinematic:.0f}",
            f"tech={scores.technical:.0f}",
        ]
        if approved:
            summary = "APPROVED — " + ", ".join(summary_parts)
        else:
            summary = (
                f"NEEDS_FIX ({len(priority)} actions) — "
                + ", ".join(summary_parts)
            )

        return EvaluationResult(
            project_id=project_id,
            agent_name="evaluation",
            feedback_round=1,
            approved=approved,
            overall_score=overall,
            scores=scores,
            issues=issues,
            priority_fixes=priority,
            summary=summary,
            llm_used=llm_used,
        )
