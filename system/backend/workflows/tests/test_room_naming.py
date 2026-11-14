"""Tests for Room Naming Normalization Layer."""

from backend.schemas.vision_schema import (
    RawSegment,
    RoomKnowledge,
    SpaceInventoryItem,
    VideoIndex,
    VKBSegment,
    VisionKnowledgeBase,
)
from backend.workflows.room_naming import (
    make_instance_id,
    narration_label,
    normalize_room_names,
)


def _vkb(spaces_by_seg: list[list[SpaceInventoryItem]]) -> VisionKnowledgeBase:
    segments = []
    t = 0.0
    for i, spaces in enumerate(spaces_by_seg, start=1):
        segments.append(
            VKBSegment(
                segment_id=f"seg_{i:02d}",
                raw=RawSegment(start_time=t, end_time=t + 5, duration=5),
                knowledge=RoomKnowledge(room_type="Mixed Private Area", spaces=spaces),
            )
        )
        t += 5
    return VisionKnowledgeBase(video=VideoIndex(duration=t), segments=segments)


def test_kitchen_instance_never_spoken() -> None:
    vkb = _vkb(
        [
            [
                SpaceInventoryItem(
                    type="Kitchen",
                    instance=2,
                    instance_id="Kitchen_2",
                    display_name="Kitchen 2",
                    features=["cooktop"],
                )
            ]
        ]
    )
    normalize_room_names(vkb)
    space = vkb.segments[0].knowledge.spaces[0]
    assert space.instance_id == "Kitchen_2"
    assert space.instance == 2
    assert space.display_name == "Kitchen"
    assert space.narration_name == "Kitchen"
    assert space.room_role == "shared"
    assert narration_label(space) == "Kitchen"


def test_primary_bedroom_from_evidence() -> None:
    vkb = _vkb(
        [
            [
                SpaceInventoryItem(
                    type="Bedroom",
                    instance=1,
                    display_name="Bedroom 1",
                    features=["twin bed"],
                ),
                SpaceInventoryItem(
                    type="Bedroom",
                    instance=4,
                    display_name="Bedroom 4",
                    features=["king bed", "ensuite", "walk-in closet"],
                    confidence=0.95,
                ),
            ]
        ]
    )
    normalize_room_names(vkb)
    by_id = {s.instance_id: s for s in vkb.segments[0].knowledge.spaces}
    assert by_id["Bedroom_4"].narration_name == "Primary Bedroom"
    assert by_id["Bedroom_4"].room_role == "primary"
    assert by_id["Bedroom_1"].narration_name == "Bedroom"
    assert by_id["Bedroom_1"].display_name == "Bedroom"
    assert by_id["Bedroom_1"].room_role == "secondary"
    assert all(not any(c.isdigit() for c in s.narration_name) for s in by_id.values())


def test_study_becomes_study_area() -> None:
    vkb = _vkb(
        [[SpaceInventoryItem(type="Study Room", instance=3, display_name="Study Room 3")]]
    )
    normalize_room_names(vkb)
    space = vkb.segments[0].knowledge.spaces[0]
    assert space.instance_id == "Study_Room_3"
    assert space.narration_name == "Study Area"
    assert space.display_name == "Study Area"


def test_make_instance_id() -> None:
    assert make_instance_id("Bedroom", 4) == "Bedroom_4"
    assert make_instance_id("Study Room", 1) == "Study_Room_1"


def test_idempotent() -> None:
    vkb = _vkb(
        [[SpaceInventoryItem(type="Kitchen", instance=2, display_name="Kitchen 2")]]
    )
    normalize_room_names(vkb)
    first = vkb.segments[0].knowledge.spaces[0].model_dump()
    normalize_room_names(vkb)
    assert vkb.segments[0].knowledge.spaces[0].model_dump() == first


def test_guest_without_bed_is_not_guest_bedroom() -> None:
    vkb = _vkb(
        [
            [
                SpaceInventoryItem(
                    type="Bedroom",
                    instance=1,
                    features=["guest", "orange sofa"],
                ),
                SpaceInventoryItem(
                    type="Bedroom",
                    instance=2,
                    features=["bed", "window"],
                ),
            ]
        ]
    )
    normalize_room_names(vkb)
    names = {s.instance_id: s.narration_name for s in vkb.segments[0].knowledge.spaces}
    assert names["Bedroom_1"] == "Bedroom"
    assert names["Bedroom_2"] == "Bedroom"
    assert all(s.narration_name != "Guest Bedroom" for s in vkb.segments[0].knowledge.spaces)


def test_guest_with_bed_keeps_guest_label() -> None:
    vkb = _vkb(
        [
            [
                SpaceInventoryItem(
                    type="Bedroom",
                    instance=1,
                    features=["guest bedroom", "bed", "nightstand"],
                    confidence=0.9,
                ),
                SpaceInventoryItem(
                    type="Bedroom",
                    instance=2,
                    features=["king bed", "ensuite"],
                    confidence=0.95,
                ),
            ]
        ]
    )
    normalize_room_names(vkb)
    by_id = {s.instance_id: s.narration_name for s in vkb.segments[0].knowledge.spaces}
    assert by_id["Bedroom_1"] == "Guest Bedroom"
    assert by_id["Bedroom_2"] == "Primary Bedroom"


def test_undetermined_bedrooms_are_not_ranked() -> None:
    vkb = _vkb(
        [
            [
                SpaceInventoryItem(type="Bedroom", instance=1, features=["bed"]),
                SpaceInventoryItem(type="Bedroom", instance=2, features=["bed", "window"]),
            ]
        ]
    )
    normalize_room_names(vkb)
    names = {s.instance_id: s.narration_name for s in vkb.segments[0].knowledge.spaces}
    assert names["Bedroom_1"] == "Bedroom"
    assert names["Bedroom_2"] == "Bedroom"
    assert all(s.narration_name != "Secondary Bedroom" for s in vkb.segments[0].knowledge.spaces)
