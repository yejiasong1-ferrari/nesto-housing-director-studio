"""Role-based cinematic vocabulary and execution hint mapping.

Deterministic strategies per HERO / SUPPORT / TRANSITION role.
"""

from __future__ import annotations

from backend.agents.planner.attention.normalizer import (
    ROLE_HERO,
    ROLE_SUPPORT,
    ROLE_TRANSITION,
)
from backend.schemas.planning_schema import CinematicStrategy, DirectorIntent

ROLE_EXECUTION_HINTS: dict[str, list[str]] = {
    ROLE_HERO: [
        "slow_push_in",
        "zoom",
        "object_highlight",
        "subtitle_callout",
        "cinematic_emphasis",
    ],
    ROLE_SUPPORT: [
        "standard_pace",
        "gentle_pan",
        "light_subtitle",
    ],
    ROLE_TRANSITION: [
        "fade",
        "fast_cut",
        "motion_blur",
    ],
}

ROLE_EDITING_INTENT: dict[str, str] = {
    ROLE_HERO: "heroization",
    ROLE_SUPPORT: "supportive_highlight",
    ROLE_TRANSITION: "transitional_pace",
}

ROLE_CAMERA_LANGUAGE: dict[str, str] = {
    ROLE_HERO: "slow_push_in + depth_emphasis",
    ROLE_SUPPORT: "standard_coverage + gentle_pan",
    ROLE_TRANSITION: "transitional_pace + motion_blur",
}

ROLE_ATTENTION_GUIDANCE: dict[str, str] = {
    ROLE_HERO: "primary_feature_then_depth",
    ROLE_SUPPORT: "balanced_coverage",
    ROLE_TRANSITION: "maintain_flow",
}


def get_role_execution_hints(role: str, room_type: str = "", intent_tags: list[str] | None = None) -> list[str]:
    """Return deterministic execution hints for a segment role."""
    hints = list(ROLE_EXECUTION_HINTS.get(role, ROLE_EXECUTION_HINTS[ROLE_SUPPORT]))
    tags = intent_tags or []

    if role == ROLE_HERO and "kitchen" in room_type.lower():
        if "object_highlight" not in hints:
            hints.insert(0, "object_highlight")
    if role == ROLE_HERO and "highlight_natural_light" in tags:
        if "subtitle_callout" in hints:
            hints = ["slow_push_in", "subtitle_callout", "cinematic_emphasis"] + [
                h for h in hints if h not in {"slow_push_in", "subtitle_callout", "cinematic_emphasis"}
            ]

    return list(dict.fromkeys(hints))


def build_role_cinematic(
    segment_id: str,
    role: str,
    intent: DirectorIntent,
    room_type: str = "",
    focus_points: list[str] | None = None,
) -> CinematicStrategy:
    """Build cinematic strategy deterministically from attention role."""
    focus_points = focus_points or []
    execution_hints = get_role_execution_hints(role, room_type, intent.intent_tags)
    editing_intent = ROLE_EDITING_INTENT.get(role, "supportive_highlight")
    camera_language = ROLE_CAMERA_LANGUAGE.get(role, "standard_coverage")
    attention_guidance = ROLE_ATTENTION_GUIDANCE.get(role, "balanced_coverage")
    emotion_engine = intent.intent_graph.emotional_target or intent.emotional_tone or "neutral"

    if role == ROLE_HERO:
        if "highlight_natural_light" in intent.intent_tags:
            attention_guidance = "window_light_first_then_feature"
        elif focus_points:
            attention_guidance = f"{focus_points[0][:40]}_then_space"
    elif role == ROLE_TRANSITION:
        attention_guidance = "de_emphasize_narration"

    return CinematicStrategy(
        segment_id=segment_id,
        camera_language=camera_language,
        attention_guidance=attention_guidance,
        emotion_engine=emotion_engine,
        editing_intent=editing_intent,
        execution_hints=execution_hints,
    )


def enrich_with_execution(strategy: CinematicStrategy) -> CinematicStrategy:
    """Ensure execution_hints are populated."""
    if not strategy.execution_hints:
        strategy.execution_hints = ROLE_EXECUTION_HINTS.get(
            ROLE_SUPPORT,
            ["standard_pace"],
        )
    return strategy
