"""Tests for Space Coverage Controller (Narration Planner + Checker)."""

from backend.agents.script.pipeline.marketing_enricher import sanitize_unverified_room_ranks
from backend.agents.script.pipeline.space_coverage import (
    build_coverage_plans,
    build_segment_coverage_plan,
    check_coverage,
)
from backend.schemas.vision_schema import (
    RawSegment,
    RoomKnowledge,
    SpaceInventoryItem,
    VideoIndex,
    VKBSegment,
    VisionKnowledgeBase,
)
from backend.workflows.room_naming import normalize_room_names


def _seg(sid: str, spaces: list[SpaceInventoryItem], start: float = 0.0) -> VKBSegment:
    return VKBSegment(
        segment_id=sid,
        raw=RawSegment(start_time=start, end_time=start + 10, duration=10),
        knowledge=RoomKnowledge(room_type="Mixed Private Area", spaces=spaces, confidence=0.9),
    )


def test_kitchen_bathroom_plan_requires_both() -> None:
    seg = _seg(
        "seg_09",
        [
            SpaceInventoryItem(
                type="Kitchen",
                instance=2,
                instance_id="Kitchen_2",
                display_name="Kitchen",
                narration_name="Kitchen",
                room_role="shared",
                confidence=0.95,
                features=["cooktop", "black countertop"],
            ),
            SpaceInventoryItem(
                type="Bathroom",
                instance=1,
                instance_id="Bathroom_1",
                display_name="Bathroom",
                narration_name="Bathroom",
                room_role="utility",
                confidence=0.92,
                features=["toilet", "shower"],
            ),
        ],
        start=45,
    )
    plan = build_segment_coverage_plan(
        seg,
        segment_role="HERO",
        narrative_function="present kitchen-bathroom hybrid | cover spaces: Kitchen, Bathroom",
        video_duration=55,
    )
    assert plan.main_space is not None
    assert plan.main_space.narration_name == "Kitchen"
    assert "Bathroom" in plan.must_mention
    assert "Kitchen" in plan.must_mention
    assert any(s.narration_name == "Bathroom" and s.mention_required for s in plan.secondary_spaces)


def test_coverage_checker_detects_missing_bathroom() -> None:
    seg = _seg(
        "seg_09",
        [
            SpaceInventoryItem(type="Kitchen", narration_name="Kitchen", room_role="shared", confidence=0.9),
            SpaceInventoryItem(type="Bathroom", narration_name="Bathroom", room_role="utility", confidence=0.9),
        ],
    )
    vkb = VisionKnowledgeBase(video=VideoIndex(duration=55), segments=[seg])
    plans = build_coverage_plans(
        vkb,
        {
            "attention_map": [{"segment_id": "seg_09", "role": "HERO"}],
            "narrative_flow": [
                {
                    "segment_id": "seg_09",
                    "narrative_function": "cover spaces: Kitchen, Bathroom",
                }
            ],
        },
    )
    failed = check_coverage(
        {"seg_09": "黑色台面搭配燃气灶，打造现代厨房体验。"},
        plans,
    )
    assert failed.coverage_failed is True
    assert "Bathroom" in failed.missing_by_segment["seg_09"]

    ok = check_coverage(
        {"seg_09": "厨房黑台面配燃气灶，一旁卫生间配备淋浴，生活更便利。"},
        plans,
    )
    assert ok.coverage_failed is False


def test_hallway_optional_not_required() -> None:
    seg = _seg(
        "seg_03",
        [
            SpaceInventoryItem(
                type="Hallway",
                narration_name="Hallway",
                room_role="transit",
                confidence=0.8,
            )
        ],
    )
    plan = build_segment_coverage_plan(seg, segment_role="TRANSITION", video_duration=55)
    # Only hallway → becomes main but optional tier alone may still be must for main
    # Hallway alone: becomes main_space with mention_required True (need something to say)
    assert plan.main_space is not None
    assert plan.main_space.narration_name == "Hallway"


def test_build_plans_with_normalize() -> None:
    vkb = VisionKnowledgeBase(
        video=VideoIndex(duration=55),
        segments=[
            _seg(
                "seg_09",
                [
                    SpaceInventoryItem(type="Kitchen", instance=2, display_name="Kitchen 2", confidence=0.9),
                    SpaceInventoryItem(
                        type="Bathroom",
                        instance=1,
                        display_name="Bathroom",
                        confidence=0.9,
                        features=["toilet"],
                    ),
                ],
                start=45,
            )
        ],
    )
    normalize_room_names(vkb)
    plans = build_coverage_plans(vkb, {"attention_map": [{"segment_id": "seg_09", "role": "HERO"}]})
    assert "Bathroom" in plans["seg_09"].must_mention
    assert "Kitchen" in plans["seg_09"].must_mention


def test_laundry_not_named_from_living_room() -> None:
    seg = _seg(
        "seg_10",
        [
            SpaceInventoryItem(
                type="Living Room",
                narration_name="Living Room",
                room_role="primary",
                confidence=0.95,
                features=["orange sofa", "rug"],
            ),
            SpaceInventoryItem(
                type="Laundry Room",
                narration_name="Laundry",
                room_role="secondary",
                confidence=0.9,
                features=["washer", "dryer"],
            ),
        ],
        start=70,
    )
    plan = build_segment_coverage_plan(seg, segment_role="SUPPORT", video_duration=110)
    assert plan.main_space is not None
    assert plan.main_space.narration_name == "Living Room"
    assert "Laundry" not in plan.must_mention
    assert "Laundry Room" not in plan.must_mention


def test_sanitize_drops_guessed_ranks() -> None:
    assert (
        sanitize_unverified_room_ranks(
            "书房旁的独立卫生间很整洁。",
            must_mention=["Bathroom"],
            main_space="Bathroom",
        )
        == "独立卫生间很整洁。"
    )
    assert "客卧" not in sanitize_unverified_room_ranks(
        "眼前是客卧：橙色沙发。",
        must_mention=["Living Room"],
        main_space="Living Room",
    )
    assert "主卧" not in sanitize_unverified_room_ranks(
        "最后来到次卧，粉色床品。",
        must_mention=["Bedroom"],
        main_space="Bedroom",
    )
    assert "主卫" not in sanitize_unverified_room_ranks(
        "这是主卫，配备马桶。",
        must_mention=["Bathroom"],
        main_space="Bathroom",
    )
    # Adjacent phrase kept only when previous primary is confirmed + continuous.
    kept = sanitize_unverified_room_ranks(
        "书房旁的独立卫生间很整洁。",
        must_mention=["Bathroom"],
        main_space="Bathroom",
        previous_primary="Study Area",
        adjacent_ok=True,
    )
    assert kept.startswith("书房旁的")
    dropped = sanitize_unverified_room_ranks(
        "客厅旁的厨房很亮。",
        must_mention=["Kitchen"],
        main_space="Kitchen",
        previous_primary="Hallway",
        adjacent_ok=True,
    )
    assert "客厅旁的" not in dropped
    assert "厨房" in dropped


def test_sanitize_bath_rank_keeps_word_intact() -> None:
    """次卫生间 must lose only the rank char, not become 卫生间生间."""
    out = sanitize_unverified_room_ranks(
        "这是次卫生间，配玻璃淋浴房。",
        must_mention=["Bathroom"],
        main_space="Bathroom",
    )
    assert out == "这是卫生间，配玻璃淋浴房。"
    assert "生间生间" not in out


def test_sanitize_drops_adjacent_room_tail_clause() -> None:
    """The shot is the bathroom; the bedroom next door is not ours to describe."""
    out = sanitize_unverified_room_ranks(
        "卫生间配壁挂马桶与悬浮洗漱台，镜面集成照明；旁为卧室，床品整洁，落地窗采光充足。",
        must_mention=["Bathroom"],
        main_space="Bathroom",
    )
    assert out == "卫生间配壁挂马桶与悬浮洗漱台，镜面集成照明。"

    out2 = sanitize_unverified_room_ranks(
        "推门即达阳台——玻璃栏杆配户外座椅；旁侧客厅的橙色沙发与大窗相连，暖意延展。",
        must_mention=["Balcony"],
        main_space="Balcony",
    )
    assert "客厅" not in out2
    assert out2.endswith("。")
