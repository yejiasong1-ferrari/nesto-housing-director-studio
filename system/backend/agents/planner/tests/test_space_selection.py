"""Tests for duration-aware narration space selection."""

from backend.agents.planner.narrative.space_selection import (
    apply_space_narration_selection,
    narration_plan_for_segment,
)
from backend.schemas.planning_schema import NarrativeEntry
from backend.schemas.vision_schema import (
    RawSegment,
    RoomKnowledge,
    SpaceInventoryItem,
    VideoIndex,
    VKBSegment,
    VisionKnowledgeBase,
)


def _seg(seg_id: str, start: float, end: float, spaces: list[SpaceInventoryItem], room: str) -> VKBSegment:
    return VKBSegment(
        segment_id=seg_id,
        confidence=0.9,
        raw=RawSegment(start_time=start, end_time=end, duration=end - start),
        knowledge=RoomKnowledge(room_type=room, spaces=spaces, confidence=0.9),
    )


def test_short_video_summarizes_multiple_bedrooms() -> None:
    from backend.workflows.room_naming import normalize_segment_spaces

    seg = _seg(
        "seg_03",
        9.0,
        20.7,
        [
            SpaceInventoryItem(type="Bedroom", instance=1, instance_id="Bedroom_1"),
            SpaceInventoryItem(type="Bedroom", instance=2, instance_id="Bedroom_2"),
            SpaceInventoryItem(type="Study Room", instance=1, instance_id="Study_Room_1"),
        ],
        "Mixed Private Area",
    )
    normalize_segment_spaces([seg])
    plan = narration_plan_for_segment(seg, video_duration=20.7)
    assert plan["mode"] == "summary"
    assert len(plan["summary_spaces"]) >= 2
    assert all(not any(ch.isdigit() for ch in label) for label in plan["summary_spaces"])


def test_apply_annotates_narrative_function() -> None:
    from backend.workflows.room_naming import normalize_room_names

    vkb = VisionKnowledgeBase(
        video=VideoIndex(duration=20.7),
        segments=[
            _seg(
                "seg_03",
                9.0,
                20.7,
                [
                    SpaceInventoryItem(type="Bedroom", instance=1, instance_id="Bedroom_1"),
                    SpaceInventoryItem(type="Bedroom", instance=2, instance_id="Bedroom_2"),
                ],
                "Bedroom",
            )
        ],
    )
    normalize_room_names(vkb)
    flow = [NarrativeEntry(segment_id="seg_03", role="HERO", narrative_function="showcase")]
    apply_space_narration_selection(vkb, flow)
    assert "summarize private spaces" in flow[0].narrative_function
    assert "Bedroom 1" not in flow[0].narrative_function
    assert "Bedroom_1" not in flow[0].narrative_function
