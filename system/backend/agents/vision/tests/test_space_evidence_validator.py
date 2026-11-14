"""Phase 1–2 tests: Verified Space Layer + Hero Score."""

from backend.agents.script.pipeline.space_coverage import build_segment_coverage_plan
from backend.agents.vision.modules.space_evidence_validator import (
    hero_score,
    validate_segment_spaces,
    validate_space,
)
from backend.schemas.vision_schema import (
    RawSegment,
    RoomKnowledge,
    SpaceInventoryItem,
    VKBSegment,
)


def test_phase1_reject_speculative_bathroom_11() -> None:
    seg = VKBSegment(
        segment_id="seg_02",
        raw=RawSegment(start_time=4, end_time=9, duration=5),
        knowledge=RoomKnowledge(
            room_type="Kitchen",
            confidence=0.95,
            selling_points=[
                "Galley-style kitchen with stainless steel appliances",
                "Visible hallway leading to interior doors (likely bedrooms/bathroom)",
            ],
            appliances=["Gas cooktop", "Refrigerator"],
            spaces=[
                SpaceInventoryItem(
                    type="Kitchen",
                    confidence=0.95,
                    features=["cooktop", "range hood", "refrigerator"],
                ),
                SpaceInventoryItem(
                    type="Bathroom",
                    confidence=0.76,
                    features=[
                        "Visible hallway leading to interior doors (likely bedrooms/bathroom)"
                    ],
                ),
            ],
        ),
    )
    validate_segment_spaces(seg)
    types = {s.type for s in seg.knowledge.spaces}
    assert "Kitchen" in types
    assert "Bathroom" not in types


def test_phase1_reject_fake_kitchen_on_bedroom_6() -> None:
    seg = VKBSegment(
        segment_id="seg_08",
        raw=RawSegment(start_time=38, end_time=45, duration=7),
        knowledge=RoomKnowledge(
            room_type="Bedroom",
            confidence=0.95,
            notes="primary=Bedroom",
            selling_points=[
                "Large bay window with multiple panes",
                "Window sill used as display shelf",
                "Built-in wardrobe visible on left wall",
            ],
            furniture=[
                "Bed (partially visible, with patterned bedding)",
                "Desk (with laptop, notebook)",
                "Wardrobe (white, built-in)",
            ],
            appliances=["Wall-mounted air conditioner"],
            spaces=[
                SpaceInventoryItem(
                    type="Bedroom",
                    confidence=0.95,
                    features=["bed", "curtains", "window", "bedroom"],
                ),
                SpaceInventoryItem(
                    type="Kitchen",
                    confidence=0.9,
                    features=["white upper cabinets", "open shelf", "hanging pans", "cooktop"],
                ),
                SpaceInventoryItem(
                    type="Study Room",
                    confidence=0.85,
                    features=["Desk (with laptop)", "Lamp"],
                ),
            ],
        ),
    )
    validate_segment_spaces(seg)
    types = {s.type for s in seg.knowledge.spaces}
    assert "Bedroom" in types
    assert "Kitchen" not in types  # Module-4 bedroom wins over hallucinated kitchen


def test_phase1_keep_real_kitchen_bathroom_on_seg09() -> None:
    seg = VKBSegment(
        segment_id="seg_09",
        raw=RawSegment(start_time=45, end_time=55, duration=10),
        knowledge=RoomKnowledge(
            room_type="Mixed Private Area",
            confidence=0.95,
            selling_points=[
                "Black countertop with gas cooktop",
                "Glass-enclosed shower stall",
                "Tiled accent border in washroom",
            ],
            appliances=["Gas cooktop", "Showerhead with handheld attachment"],
            furniture=["Upper wall cabinets", "Vanity (partial)"],
            spaces=[
                SpaceInventoryItem(
                    type="Kitchen",
                    confidence=0.95,
                    features=["cooktop", "black countertop", "white cabinets"],
                ),
                SpaceInventoryItem(
                    type="Bathroom",
                    confidence=0.92,
                    features=["glass shower enclosure", "showerhead", "toilet", "vanity"],
                ),
            ],
        ),
    )
    validate_segment_spaces(seg)
    types = {s.type for s in seg.knowledge.spaces}
    assert "Kitchen" in types
    assert "Bathroom" in types
    bath = next(s for s in seg.knowledge.spaces if s.type == "Bathroom")
    assert bath.evidence.verified is True
    assert bath.evidence.hard_features


def test_phase2_bedroom_beats_weak_kitchen_as_hero() -> None:
    # Simulate post-validation spaces (bedroom verified, no kitchen)
    seg = VKBSegment(
        segment_id="seg_08",
        raw=RawSegment(start_time=38, end_time=45, duration=7),
        knowledge=RoomKnowledge(
            room_type="Bedroom",
            spaces=[
                SpaceInventoryItem(
                    type="Bedroom",
                    confidence=0.9,
                    features=["bed", "curtains"],
                    narration_name="Bedroom Area",
                ),
                SpaceInventoryItem(
                    type="Study Room",
                    confidence=0.8,
                    features=["desk", "laptop"],
                    narration_name="Study Area",
                ),
            ],
        ),
    )
    validate_segment_spaces(seg)
    plan = build_segment_coverage_plan(seg, segment_role="SUPPORT", video_duration=55)
    assert plan.main_space is not None
    assert "Kitchen" not in plan.must_mention
    assert "Study Area" not in plan.must_mention
    assert plan.main_space.narration_name in ("Bedroom Area", "Bedroom")
    # A desk in a bedroom is not a dedicated study.
    assert all(s.type != "Study Room" for s in seg.knowledge.spaces)
    bed = next(s for s in seg.knowledge.spaces if s.type == "Bedroom")
    assert hero_score(bed) > 0


def test_laundry_does_not_steal_living_room_primary() -> None:
    seg = VKBSegment(
        segment_id="seg_10",
        raw=RawSegment(start_time=70, end_time=83, duration=13),
        knowledge=RoomKnowledge(
            room_type="Mixed Private Area",
            confidence=0.9,
            selling_points=["orange sofa", "stacked washer and dryer"],
            furniture=["orange sofa", "rug"],
            appliances=["washer", "dryer"],
            spaces=[
                SpaceInventoryItem(
                    type="Living Room",
                    confidence=0.9,
                    features=["orange sofa", "wavy-pattern rug"],
                ),
                SpaceInventoryItem(
                    type="Laundry Room",
                    confidence=0.95,
                    features=["stacked washer", "front-load dryer"],
                ),
            ],
        ),
    )
    validate_segment_spaces(seg)
    primary = next(s for s in seg.knowledge.spaces if s.room_role == "primary")
    assert primary.type == "Living Room"
    laundry = next(s for s in seg.knowledge.spaces if s.type == "Laundry Room")
    assert laundry.room_role in ("secondary", "glimpse")


def test_dishwasher_is_not_a_washer() -> None:
    from backend.agents.vision.modules.space_evidence_validator import _keyword_in_text

    assert not _keyword_in_text("washer", "Built-in dishwasher with open rack")
    assert _keyword_in_text("washer", "stacked washer")
    assert not _keyword_in_text("bed", "Bedroom")
    assert _keyword_in_text("bed", "Bed with gray bedding")


def test_dishwasher_segment_becomes_kitchen_not_laundry() -> None:
    seg = VKBSegment(
        segment_id="seg_03",
        raw=RawSegment(start_time=13, end_time=17, duration=4),
        knowledge=RoomKnowledge(
            room_type="Laundry Room",
            confidence=0.98,
            selling_points=["Built-in dishwasher with open rack visible", "Stainless steel undermount sink"],
            appliances=["Dishwasher (built-in, front-control panel)", "Sink (stainless steel, undermount)"],
            spaces=[
                SpaceInventoryItem(
                    type="Living Room",
                    confidence=0.4,
                    features=["large windows"],
                ),
                SpaceInventoryItem(
                    type="Laundry Room",
                    confidence=0.98,
                    features=[
                        "Built-in dishwasher with open rack visible",
                        "Dishwasher (built-in, front-control panel)",
                    ],
                ),
            ],
        ),
    )
    validate_segment_spaces(seg)
    types = {s.type for s in seg.knowledge.spaces}
    assert "Laundry Room" not in types
    assert "Kitchen" in types
    primary = next(s for s in seg.knowledge.spaces if s.room_role == "primary")
    assert primary.type == "Kitchen"


def test_hallway_loses_to_living_when_windows_fill_the_shot() -> None:
    seg = VKBSegment(
        segment_id="seg_15",
        raw=RawSegment(start_time=103, end_time=118, duration=15),
        knowledge=RoomKnowledge(
            room_type="Hallway",
            confidence=0.95,
            selling_points=["Floor-to-ceiling windows with city view", "Dark hardwood flooring"],
            spaces=[
                SpaceInventoryItem(
                    type="Living Room",
                    confidence=0.4,
                    features=["large floor-to-ceiling windows"],
                ),
                SpaceInventoryItem(
                    type="Hallway",
                    confidence=0.95,
                    features=["multiple closed doors", "dark flooring"],
                ),
            ],
        ),
    )
    validate_segment_spaces(seg)
    primary = next(s for s in seg.knowledge.spaces if s.room_role == "primary")
    assert primary.type == "Living Room"
