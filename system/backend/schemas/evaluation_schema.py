"""Evaluation Agent schema — single feedback loop (final review pass).

One evaluation → one structured feedback → apply once → final render.
Evaluation Agent does not participate again.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


class CategoryScores(BaseModel):
    """Weighted category scores on 0–100 scale."""

    audiovisual: float = 0.0   # 40%
    subtitle: float = 0.0      # 15%
    timeline: float = 0.0      # 20%
    cinematic: float = 0.0     # 15%
    technical: float = 0.0     # 10%


class EvaluationIssue(BaseModel):
    """One detected quality issue before LLM attribution."""

    type: str = ""
    segment_id: str = ""
    severity: str = "medium"   # low | medium | high
    description: str = ""
    evidence: dict = Field(default_factory=dict)
    suggested_target: str = ""  # timeline | editing | script | voice | rendering


class FixAction(BaseModel):
    type: str = ""
    value: Optional[Any] = None
    target: str = ""


class PriorityFix(BaseModel):
    id: str = ""
    target_agent: str = ""     # timeline_agent | editing_agent | script_agent
    segment: str = ""
    problem: str = ""
    action: FixAction = Field(default_factory=FixAction)
    severity: str = "medium"
    root_cause: str = ""


class EvaluationResult(VersionedBaseModel):
    """Complete Evaluation Agent output — produced exactly once per production."""

    agent_name: str = "evaluation"
    feedback_round: int = 1
    approved: bool = False
    overall_score: float = 0.0  # 0–100
    scores: CategoryScores = Field(default_factory=CategoryScores)
    issues: list[EvaluationIssue] = Field(default_factory=list)
    priority_fixes: list[PriorityFix] = Field(default_factory=list)
    summary: str = ""
    llm_used: bool = False


# Backward-compat aliases for older stubs
class QualityMetrics(BaseModel):
    narration_sync: float = 0.0
    subtitle_quality: float = 0.0
    visual_continuity: float = 0.0
    highlight_coverage: float = 0.0
    pacing: float = 0.0
    editing_smoothness: float = 0.0
