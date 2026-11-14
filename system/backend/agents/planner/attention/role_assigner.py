"""Build AttentionHierarchy from normalized attention entries."""

from __future__ import annotations

from backend.agents.planner.attention.normalizer import (
    ROLE_HERO,
    ROLE_SUPPORT,
    ROLE_TRANSITION,
)
from backend.schemas.planning_schema import AttentionEntry, AttentionHierarchy


def build_hierarchy(entries: list[AttentionEntry]) -> AttentionHierarchy:
    """Collect segment IDs by assigned role."""
    hero: list[str] = []
    support: list[str] = []
    transition: list[str] = []

    for entry in entries:
        if entry.role == ROLE_HERO:
            hero.append(entry.segment_id)
        elif entry.role == ROLE_TRANSITION:
            transition.append(entry.segment_id)
        else:
            support.append(entry.segment_id)

    return AttentionHierarchy(
        hero_segments=hero,
        support_segments=support,
        transition_segments=transition,
    )
