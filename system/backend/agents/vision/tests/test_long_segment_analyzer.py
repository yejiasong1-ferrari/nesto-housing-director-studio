"""Unit tests for long-segment space inventory helpers."""

from pathlib import Path

import numpy as np

from backend.agents.vision.modules.long_segment_analyzer import (
    assign_instances,
    extract_evidence_rooms,
    filter_quality_frames,
    has_room_evidence_conflict,
    merge_evidence_into_spaces,
    primary_room_type,
    score_frame_quality,
    should_reanalyze,
    spaces_from_primary,
)
from backend.schemas.vision_schema import RawSegment, RoomKnowledge, SpaceInventoryItem, VKBSegment


def test_assign_instances_numbers_duplicate_bedrooms() -> None:
    items = assign_instances(
        [
            SpaceInventoryItem(type="Bedroom", confidence=0.9),
            SpaceInventoryItem(type="Bedroom", confidence=0.8),
            SpaceInventoryItem(type="Study Room", confidence=0.7),
        ]
    )
    # Interim technical labels; Room Naming Normalization rewrites before Planner.
    assert [s.display_name for s in items] == ["Bedroom 1", "Bedroom 2", "Study Room"]
    assert [s.instance for s in items] == [1, 2, 1]
    assert [s.instance_id for s in items] == ["Bedroom_1", "Bedroom_2", "Study_Room_1"]


def test_primary_room_type_mixed() -> None:
    spaces = assign_instances(
        [
            SpaceInventoryItem(type="Bedroom"),
            SpaceInventoryItem(type="Study Room"),
        ]
    )
    assert primary_room_type(spaces) == "Mixed Private Area"


def test_spaces_from_primary_fallback() -> None:
    spaces = spaces_from_primary(
        RoomKnowledge(room_type="Kitchen", confidence=0.9, selling_points=["Island"])
    )
    assert len(spaces) == 1
    assert spaces[0].type == "Kitchen"
    assert spaces[0].display_name == "Kitchen"


def test_evidence_conflict_kitchen_plus_shower() -> None:
    k = RoomKnowledge(
        room_type="Kitchen",
        confidence=0.95,
        selling_points=["Black countertop", "Glass-enclosed shower stall", "Washroom tile border"],
        appliances=["Gas cooktop", "Shower fixture with handheld head"],
    )
    assert has_room_evidence_conflict(k) is True
    spaces = merge_evidence_into_spaces([SpaceInventoryItem(type="Kitchen", confidence=0.95)], k)
    types = {s.type for s in spaces}
    assert "Kitchen" in types
    assert "Bathroom" in types
    bath = next(s for s in spaces if s.type == "Bathroom")
    assert bath.features  # evidence features retained


def test_speculative_likely_bathroom_not_minted() -> None:
    """Closed-door speculation must not create a Bathroom inventory item."""
    k = RoomKnowledge(
        room_type="Kitchen",
        confidence=0.95,
        selling_points=[
            "Galley-style kitchen with stainless steel appliances",
            "Visible hallway leading to interior doors (likely bedrooms/bathroom)",
        ],
        appliances=["Gas cooktop", "Refrigerator"],
    )
    # Bare "bathroom" inside speculation is not a conflict / mint trigger
    assert "Bathroom" not in extract_evidence_rooms(k)
    spaces = merge_evidence_into_spaces(
        [
            SpaceInventoryItem(type="Kitchen", confidence=0.95, features=["cooktop"]),
            SpaceInventoryItem(
                type="Bathroom",
                confidence=0.7,
                features=["Visible hallway leading to interior doors (likely bedrooms/bathroom)"],
            ),
        ],
        k,
    )
    assert all(s.type != "Bathroom" for s in spaces)


def test_finalize_drops_ungrounded_bathroom() -> None:
    from backend.agents.vision.modules.long_segment_analyzer import finalize_space_inventory

    segments = [
        VKBSegment(
            segment_id="seg_02",
            raw=RawSegment(start_time=4, end_time=9, duration=5),
            knowledge=RoomKnowledge(
                room_type="Mixed Private Area",
                spaces=[
                    SpaceInventoryItem(type="Kitchen", confidence=0.95, features=["cooktop"]),
                    SpaceInventoryItem(
                        type="Bathroom",
                        confidence=0.76,
                        features=["Visible hallway leading to interior doors (likely bedrooms/bathroom)"],
                    ),
                ],
            ),
        )
    ]
    finalize_space_inventory(segments)
    types = {s.type for s in segments[0].knowledge.spaces}
    assert "Kitchen" in types
    assert "Bathroom" not in types



def test_should_reanalyze_triggers() -> None:
    long_seg = VKBSegment(
        segment_id="seg_09",
        raw=RawSegment(start_time=45, end_time=55, duration=10),
        knowledge=RoomKnowledge(room_type="Kitchen", confidence=0.95),
    )
    assert should_reanalyze(long_seg) is True

    mixed = VKBSegment(
        segment_id="seg_x",
        raw=RawSegment(start_time=0, end_time=5, duration=5),
        knowledge=RoomKnowledge(room_type="Mixed Private Area", confidence=0.9),
    )
    assert should_reanalyze(mixed) is True

    low_conf = VKBSegment(
        segment_id="seg_y",
        raw=RawSegment(start_time=0, end_time=5, duration=5),
        knowledge=RoomKnowledge(room_type="Bedroom", confidence=0.3),
    )
    assert should_reanalyze(low_conf) is True

    conflict = VKBSegment(
        segment_id="seg_z",
        raw=RawSegment(start_time=0, end_time=5, duration=5),
        knowledge=RoomKnowledge(
            room_type="Kitchen",
            confidence=0.95,
            selling_points=["Glass-enclosed shower stall"],
        ),
    )
    assert should_reanalyze(conflict) is True

    clean = VKBSegment(
        segment_id="seg_ok",
        raw=RawSegment(start_time=0, end_time=5, duration=5),
        knowledge=RoomKnowledge(room_type="Living Room", confidence=0.95, selling_points=["Sofa"]),
    )
    assert should_reanalyze(clean) is False


def test_filter_drops_black_and_logo(tmp_path: Path) -> None:
    import cv2

    black = tmp_path / "black.jpg"
    cv2.imwrite(str(black), np.zeros((120, 160, 3), dtype=np.uint8))

    logo = tmp_path / "logo.jpg"
    canvas = np.zeros((200, 320, 3), dtype=np.uint8)
    cv2.putText(canvas, "HKULF", (90, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    cv2.imwrite(str(logo), canvas)

    room = tmp_path / "room.jpg"
    noisy = np.random.randint(40, 200, (180, 240, 3), dtype=np.uint8)
    cv2.imwrite(str(room), noisy)

    assert score_frame_quality(black)["ok"] is False
    assert score_frame_quality(logo)["ok"] is False
    assert score_frame_quality(room)["ok"] is True

    kept = filter_quality_frames([str(black), str(logo), str(room)])
    assert kept == [str(room)]


def test_finalize_dedupes_study_and_keeps_two_bedrooms() -> None:
    from backend.agents.vision.modules.long_segment_analyzer import finalize_space_inventory

    segments = [
        VKBSegment(
            segment_id="seg_01",
            raw=RawSegment(start_time=0, end_time=4, duration=4),
            knowledge=RoomKnowledge(
                room_type="Living Room",
                spaces=[SpaceInventoryItem(type="Living Room", confidence=0.9)],
            ),
        ),
        VKBSegment(
            segment_id="seg_02",
            raw=RawSegment(start_time=4, end_time=9, duration=5),
            knowledge=RoomKnowledge(
                room_type="Kitchen",
                spaces=[SpaceInventoryItem(type="Kitchen", confidence=0.9, features=["cabinets"])],
            ),
        ),
        VKBSegment(
            segment_id="seg_03",
            raw=RawSegment(start_time=9, end_time=14, duration=5),
            knowledge=RoomKnowledge(
                room_type="Mixed Private Area",
                spaces=[
                    SpaceInventoryItem(type="Kitchen", confidence=0.7, features=["cabinets"]),
                    SpaceInventoryItem(
                        type="Study Room",
                        confidence=0.9,
                        features=["desk", "chair", "bookshelf", "yoga mat"],
                    ),
                    SpaceInventoryItem(
                        type="Bedroom",
                        confidence=0.9,
                        features=["platform bed", "curtains", "wood flooring"],
                    ),
                ],
            ),
        ),
        VKBSegment(
            segment_id="seg_04",
            raw=RawSegment(start_time=14, end_time=20, duration=6),
            knowledge=RoomKnowledge(
                room_type="Mixed Private Area",
                spaces=[
                    SpaceInventoryItem(
                        type="Study Room",
                        confidence=0.85,
                        features=["desk", "chair", "bookshelf", "yoga mat"],
                    ),
                    SpaceInventoryItem(
                        type="Bedroom",
                        confidence=0.9,
                        features=["tufted headboard", "chandelier", "wardrobe"],
                    ),
                ],
            ),
        ),
    ]
    finalize_space_inventory(segments)
    by_id: dict[str, SpaceInventoryItem] = {}
    for seg in segments:
        for s in seg.knowledge.spaces:
            by_id[s.instance_id] = s
    assert "Kitchen_1" in by_id
    assert by_id["Kitchen_1"].narration_name == "Kitchen"
    assert "Study_Room_1" in by_id
    assert by_id["Study_Room_1"].narration_name == "Study Area"
    assert "Bedroom_1" in by_id and "Bedroom_2" in by_id
    for bid in ("Bedroom_1", "Bedroom_2"):
        assert by_id[bid].instance_id == bid
        assert "4" not in by_id[bid].narration_name
        assert not any(ch.isdigit() for ch in by_id[bid].narration_name)
        assert by_id[bid].display_name in ("Bedroom", "Primary Bedroom")
    assert all(s.type != "Kitchen" for s in segments[2].knowledge.spaces)
