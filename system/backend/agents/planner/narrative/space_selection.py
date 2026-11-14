"""Duration-aware narration space selection.

VKB holds the full property space inventory. Planner does NOT discover
spaces — it decides which inventory items deserve spoken narration given
video length.

Uses ``narration_name`` (never instance ids) for downstream Script hints.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.schemas.planning_schema import NarrativeEntry
from backend.schemas.vision_schema import SpaceInventoryItem, VKBSegment, VisionKnowledgeBase
from backend.workflows.room_naming import narration_label

logger = logging.getLogger(__name__)

# Short walkthroughs cannot narrate every bedroom individually.
SHORT_VIDEO_SECONDS = 45.0
PRIVATE_KEYWORDS = ("bedroom", "study", "office", "nursery", "guest")


def _space_label(space: SpaceInventoryItem) -> str:
    return narration_label(space)


def _is_private(space: SpaceInventoryItem | str) -> bool:
    if isinstance(space, SpaceInventoryItem):
        blob = f"{space.type} {narration_label(space)} {space.room_role}".lower()
    else:
        blob = (space or "").lower()
    return any(k in blob for k in PRIVATE_KEYWORDS)


def segment_space_labels(segment: VKBSegment) -> list[str]:
    spaces = segment.knowledge.spaces or []
    if spaces:
        return [_space_label(s) for s in spaces if _space_label(s)]
    room = (segment.knowledge.room_type or "").strip()
    return [room] if room else []


def flatten_property_spaces(vkb: VisionKnowledgeBase) -> list[str]:
    """Ordered unique display labels across the whole property."""
    seen: set[str] = set()
    out: list[str] = []
    for seg in sorted(vkb.segments, key=lambda s: s.raw.start_time):
        for label in segment_space_labels(seg):
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(label)
    return out


def narration_plan_for_segment(
    segment: VKBSegment,
    video_duration: float,
) -> dict[str, Any]:
    """Decide how Script should talk about this segment's spaces."""
    labels = segment_space_labels(segment)
    private = [l for l in labels if _is_private(l)]
    public = [l for l in labels if not _is_private(l)]

    # Short video + multiple private rooms → one summary line, not a tour of each.
    if video_duration <= SHORT_VIDEO_SECONDS and len(private) >= 2:
        return {
            "mode": "summary",
            "spaces_to_narrate": public + private[:1],
            "summary_spaces": private,
            "hint": (
                "Summarize multiple private rooms in one sentence "
                "(comfortable bedrooms / practical layouts). "
                "Do NOT name every bedroom instance."
            ),
        }

    if len(labels) >= 3 and video_duration <= SHORT_VIDEO_SECONDS:
        return {
            "mode": "summary",
            "spaces_to_narrate": labels[:2],
            "summary_spaces": labels,
            "hint": "Cover the main spaces briefly; do not list every room.",
        }

    return {
        "mode": "detail",
        "spaces_to_narrate": labels,
        "summary_spaces": [],
        "hint": "",
    }


def apply_space_narration_selection(
    vkb: VisionKnowledgeBase,
    narrative_flow: list[NarrativeEntry],
) -> list[NarrativeEntry]:
    """Annotate narrative_function with duration-aware space guidance."""
    duration = float(getattr(vkb.video, "duration", 0.0) or 0.0)
    by_id = {seg.segment_id: seg for seg in vkb.segments}

    for entry in narrative_flow:
        seg = by_id.get(entry.segment_id)
        if seg is None:
            continue
        plan = narration_plan_for_segment(seg, duration)
        labels = plan["spaces_to_narrate"]
        if plan["mode"] == "summary" and plan["summary_spaces"]:
            suffix = (
                f"summarize private spaces ({', '.join(plan['summary_spaces'])})"
            )
        elif labels:
            suffix = f"cover spaces: {', '.join(labels)}"
        else:
            continue

        base = (entry.narrative_function or "").strip()
        entry.narrative_function = f"{base} | {suffix}".strip(" |")

    property_spaces = flatten_property_spaces(vkb)
    logger.info(
        "Space narration selection: video=%.1fs property_spaces=%s",
        duration,
        property_spaces,
    )
    return narrative_flow
