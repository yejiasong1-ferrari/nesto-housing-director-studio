"""Module 1: Narrative Planner — rule-only director narrative structure.

Organizes scenes into a narrative arc (hook / explore / highlight / close).

IMPORTANT: This module does NOT re-plan editorial importance. The Planner
Agent already decided attention roles (HERO/SUPPORT/TRANSITION) and
narrative function via its own LLM + hierarchy pipeline ("Perceive/Plan
Once, Reuse Everywhere"). Narrative Planner only reformats those existing
decisions into a story-arc label per scene, in fixed video order.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.schemas.planning_schema import AttentionEntry
from backend.schemas.script_schema import NarrativeStructure
from backend.schemas.vision_schema import VisionKnowledgeBase

logger = logging.getLogger(__name__)

ARC_HOOK = "hook"
ARC_EXPLORE = "explore"
ARC_HIGHLIGHT = "highlight"
ARC_CLOSE = "close"


class NarrativePlanner:
    """Derives story_arc + scene_order from the already-computed Planner hierarchy."""

    def plan(
        self,
        vkb: VisionKnowledgeBase,
        planning: dict[str, Any],
    ) -> NarrativeStructure:
        """Build narrative structure preserving original video order."""
        segments = sorted(vkb.segments, key=lambda s: s.raw.start_time)
        scene_order = [seg.segment_id for seg in segments]

        role_by_id = self._role_by_id(planning)

        n = len(segments)
        story_arc: list[str] = []
        for i, seg in enumerate(segments):
            role = role_by_id.get(seg.segment_id, "SUPPORT")
            if i == 0:
                arc = ARC_HOOK
            elif i == n - 1:
                arc = ARC_CLOSE
            elif role == "HERO":
                arc = ARC_HIGHLIGHT
            else:
                arc = ARC_EXPLORE
            story_arc.append(arc)

        logger.info(
            "Narrative structure: %d scenes | arc=%s",
            n,
            list(zip(scene_order, story_arc))[:5],
        )
        return NarrativeStructure(story_arc=story_arc, scene_order=scene_order)

    def _role_by_id(self, planning: dict[str, Any]) -> dict[str, str]:
        attention_map = planning.get("attention_map", [])
        roles: dict[str, str] = {}
        for entry in attention_map:
            if isinstance(entry, AttentionEntry):
                roles[entry.segment_id] = entry.role or "SUPPORT"
            elif isinstance(entry, dict):
                roles[str(entry.get("segment_id", ""))] = str(entry.get("role", "SUPPORT")) or "SUPPORT"
        return roles
