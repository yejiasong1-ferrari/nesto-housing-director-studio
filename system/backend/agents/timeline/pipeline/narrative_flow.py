"""Module 4: Narrative Flow Controller.

Maps each segment group to a story phase and cinematic pace.

A real estate video should feel like a journey, not a room inventory:

  Opening Hook      → slow, atmospheric, intrigue
  Discovery         → medium, light exploration
  Living Experience → medium-slow, warmth
  Emotional Center  → slow, resonant (HERO segments)
  Core Spaces       → medium, informative
  Private Retreat   → medium, intimate
  Luxury Detail     → slow, premium reveal
  Signature Close   → slow, memorable exit

Phase assignment rules:
  arc_stage == "hook"                        → opening_hook
  arc_stage == "close"                       → signature_close
  role == "HERO" and arc_stage == "highlight" → emotional_center
  role == "HERO" and arc_stage == "explore"  → living_experience
  arc_stage == "highlight"                   → luxury_detail
  arc_stage == "explore" + position 1st third → discovery
  arc_stage == "explore" + position last 20% → private_retreat
  default                                    → core_spaces
"""

from __future__ import annotations

import logging

from backend.agents.timeline.pipeline.analyzer import EnrichedSegment
from backend.agents.timeline.pipeline.segment_optimizer import MergeGroup
from backend.schemas.timeline_schema import VisualPlan

logger = logging.getLogger(__name__)

PHASE_PACE: dict[str, str] = {
    "opening_hook": "slow",
    "discovery": "medium",
    "living_experience": "medium",
    "emotional_center": "slow",
    "core_spaces": "medium",
    "private_retreat": "medium",
    "luxury_detail": "slow",
    "signature_close": "slow",
}

CINEMATIC_INTENT: dict[str, str] = {
    "opening_hook": "establish_spatial_warmth",
    "discovery": "guide_spatial_exploration",
    "living_experience": "convey_livability",
    "emotional_center": "peak_emotional_resonance",
    "core_spaces": "inform_practical_features",
    "private_retreat": "suggest_intimacy",
    "luxury_detail": "premium_reveal",
    "signature_close": "leave_lasting_impression",
}


class NarrativeFlowController:
    """Assign story phase and pace to each merge group."""

    def plan(
        self,
        groups: list[MergeGroup],
        total_groups: int | None = None,
    ) -> list[VisualPlan]:
        n = total_groups or len(groups)
        plans: list[VisualPlan] = []
        for idx, group in enumerate(groups):
            phase = self._assign_phase(group, idx, n)
            pace = PHASE_PACE.get(phase, "medium")
            intent = CINEMATIC_INTENT.get(phase, "convey_visual_character")
            focus = self._focus_elements(group)
            plans.append(
                VisualPlan(
                    story_phase=phase,
                    pace=pace,
                    focus_elements=focus,
                    cinematic_intent=intent,
                )
            )
        return plans

    def _assign_phase(self, group: MergeGroup, idx: int, n: int) -> str:
        head = group.segments[0]
        role = head.role
        arc = head.arc_stage

        if arc == "hook":
            return "opening_hook"
        if arc == "close":
            return "signature_close"
        if role == "HERO" and arc == "highlight":
            return "emotional_center"
        if role == "HERO":
            return "living_experience"
        if arc == "highlight":
            return "luxury_detail"

        position = idx / n if n > 0 else 0
        if position < 0.3:
            return "discovery"
        if position > 0.80:
            return "private_retreat"
        return "core_spaces"

    def _focus_elements(self, group: MergeGroup) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for seg in group.segments:
            for el in seg.focus_elements:
                key = el.lower()
                if key not in seen:
                    seen.add(key)
                    result.append(el)
        return result[:4]
