"""Planner Agent schema models.

Hierarchical 5-layer output:
- intent, segment_understanding, attention_map + hierarchy
- narrative_flow, cinematic_strategy, timeline_plan
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


class IntentConstraints(BaseModel):
    preserve_video_order: bool = True


class IntentGraph(BaseModel):
    primary: str = ""
    secondary: str = ""
    emotional_target: str = ""
    avoid: list[str] = Field(default_factory=list)


class DirectorIntent(BaseModel):
    goal: str = "real_estate_marketing"
    target_audience: str = ""
    intent_tags: list[str] = Field(default_factory=list)
    emotional_tone: str = ""
    intent_graph: IntentGraph = Field(default_factory=IntentGraph)
    constraints: IntentConstraints = Field(default_factory=IntentConstraints)


class SegmentUnderstanding(BaseModel):
    """Step 2: semantic meaning per segment."""

    segment_id: str = ""
    semantic_meaning: str = ""
    visual_strength: float = 0.0
    narrative_potential: float = 0.0


class AttentionSignals(BaseModel):
    intent_match: float = 0.0
    vision: float = 0.0
    narrative_importance: float = 0.0
    object_saliency: float = 0.0
    aesthetic: float = 0.0  # diagnostic only

    @property
    def intent(self) -> float:
        return self.intent_match


class AttentionEntry(BaseModel):
    segment_id: str = ""
    score: float = 0.0
    role: str = ""  # HERO | SUPPORT | TRANSITION
    signals: AttentionSignals = Field(default_factory=AttentionSignals)
    reason: list[str] = Field(default_factory=list)


class AttentionHierarchy(BaseModel):
    hero_segments: list[str] = Field(default_factory=list)
    support_segments: list[str] = Field(default_factory=list)
    transition_segments: list[str] = Field(default_factory=list)


class NarrativeEntry(BaseModel):
    segment_id: str = ""
    role: str = ""  # HERO | SUPPORT | TRANSITION (aligned with attention)
    emotion: str = ""
    narrative_function: str = ""
    narration_weight: float = 0.5


class CinematicStrategy(BaseModel):
    segment_id: str = ""
    camera_language: str = ""
    attention_guidance: str = ""
    emotion_engine: str = ""
    editing_intent: str = ""
    execution_hints: list[str] = Field(default_factory=list)


class SegmentReasoning(BaseModel):
    segment_id: str = ""
    role: str = ""
    focus_points: list[str] = Field(default_factory=list)
    narration_weight: float = 0.5


class CameraNotes(BaseModel):
    emphasis: str = ""


class TimelinePlanEntry(BaseModel):
    segment_id: str = ""
    start: float = 0.0
    end: float = 0.0
    importance: float = 0.0
    role: str = ""
    editing_strategy: list[str] = Field(default_factory=list)
    narration_weight: float = 0.5
    camera_notes: CameraNotes = Field(default_factory=CameraNotes)
    cinematic_notes: dict[str, Any] = Field(default_factory=dict)
    narrative_role: str = ""
    cinematic_intent: str = ""


class PlannerOutput(VersionedBaseModel):
    agent_name: str = "planner"
    intent: DirectorIntent = Field(default_factory=DirectorIntent)
    segment_understanding: list[SegmentUnderstanding] = Field(default_factory=list)
    attention_map: list[AttentionEntry] = Field(default_factory=list)
    hierarchy: AttentionHierarchy = Field(default_factory=AttentionHierarchy)
    narrative_flow: list[NarrativeEntry] = Field(default_factory=list)
    cinematic_strategy: list[CinematicStrategy] = Field(default_factory=list)
    timeline_plan: list[TimelinePlanEntry] = Field(default_factory=list)
    segment_reasoning: list[SegmentReasoning] = Field(default_factory=list)

    def to_director_dict(self) -> dict[str, Any]:
        """Export director-facing JSON aligned with the planner prompt schema.

        Uses public field names (audience, tone, attention_score) and omits
        internal pipeline metadata so saved output matches the terminal summary.
        """
        intent_graph = self.intent.intent_graph
        attention_sorted = sorted(self.attention_map, key=lambda e: e.score, reverse=True)
        attention_export = [
            {
                "segment_id": entry.segment_id,
                "attention_score": round(entry.score, 2),
                "role": entry.role,
                "signals": {
                    "intent_match": round(entry.signals.intent_match, 2),
                    "vision": round(entry.signals.vision, 2),
                    "narrative_importance": round(entry.signals.narrative_importance, 2),
                    "object_saliency": round(entry.signals.object_saliency, 2),
                },
                "reason": entry.reason,
            }
            for entry in attention_sorted
        ]
        scores = [e["attention_score"] for e in attention_export]
        timeline_sorted = sorted(self.timeline_plan, key=lambda e: e.start)

        return {
            "intent": {
                "goal": self.intent.goal,
                "audience": self.intent.target_audience,
                "tone": self.intent.emotional_tone,
                "primary_focus": intent_graph.primary,
                "emotional_target": intent_graph.emotional_target,
                "intent_tags": self.intent.intent_tags,
                "avoid": intent_graph.avoid,
            },
            "hierarchy": self.hierarchy.model_dump(),
            "score_spread": {
                "min": round(min(scores), 2) if scores else 0.0,
                "max": round(max(scores), 2) if scores else 0.0,
                "range": round(max(scores) - min(scores), 2) if scores else 0.0,
            },
            "segment_understanding": [
                {
                    "segment_id": u.segment_id,
                    "semantic_meaning": u.semantic_meaning,
                    "visual_strength": round(u.visual_strength, 2),
                    "narrative_potential": round(u.narrative_potential, 2),
                }
                for u in self.segment_understanding
            ],
            "attention_map": attention_export,
            "narrative_flow": [
                {
                    "segment_id": n.segment_id,
                    "role": n.role,
                    "emotion": n.emotion,
                    "narrative_function": n.narrative_function,
                    "narration_weight": n.narration_weight,
                }
                for n in self.narrative_flow
            ],
            "cinematic_strategy": [
                {
                    "segment_id": c.segment_id,
                    "editing_intent": c.editing_intent,
                    "camera_language": c.camera_language,
                    "attention_guidance": c.attention_guidance,
                    "execution_hints": c.execution_hints,
                }
                for c in self.cinematic_strategy
            ],
            "timeline_plan": [
                {
                    "segment_id": t.segment_id,
                    "start": t.start,
                    "end": t.end,
                    "importance": round(t.importance, 2),
                    "role": t.role,
                    "narration_weight": t.narration_weight,
                    "editing_strategy": t.editing_strategy,
                    "cinematic_notes": t.cinematic_notes,
                }
                for t in timeline_sorted
            ],
        }


def planner_output_to_director_dict(output: PlannerOutput | dict[str, Any]) -> dict[str, Any]:
    """Convert PlannerOutput or planning state dict to director-facing JSON."""
    if isinstance(output, PlannerOutput):
        return output.to_director_dict()
    return PlannerOutput(**output).to_director_dict()


ContentPlan = PlannerOutput
SegmentPlan = TimelinePlanEntry
