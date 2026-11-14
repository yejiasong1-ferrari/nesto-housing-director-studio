from backend.agents.timeline.pipeline.tour_trust_guard import apply_tour_trust_guard


def _vkb_segment(seg_id: str, room: str, *, stage: str = "interior", start=0.0, visible=0.0, features=None):
    return {
        "segment_id": seg_id,
        "room_stage": stage,
        "room_visible_start": visible,
        "raw": {"start_time": start, "end_time": start + 10.0},
        "knowledge": {
            "room_type": room,
            "selling_points": features or [],
            "furniture": [],
            "appliances": features or [],
            "spaces": [
                {
                    "type": room,
                    "room_role": "primary",
                    "features": features or [],
                }
            ],
        },
    }


def test_guard_downgrades_open_dishwasher_claim() -> None:
    narration = [{
        "segment_id": "tl_001",
        "room_type": "Kitchen",
        "text": "嵌入式洗碗机门已打开，内部碗篮结构清晰可见。",
    }]
    timeline = {
        "segments": [{
            "id": "tl_001",
            "source_ids": ["seg_01"],
            "room_type": "Kitchen",
            "source": {"video_duration": 4.0},
            "duration_decision": {},
        }]
    }
    vkb = {"segments": [_vkb_segment("seg_01", "Kitchen", features=["sink", "dishwasher"])]}

    out, _, audit = apply_tour_trust_guard(narration, timeline=timeline, vkb=vkb)

    assert "门已打开" not in out[0]["text"]
    assert "碗篮" not in out[0]["text"]
    assert "洗碗机位" in out[0]["text"]
    assert audit[0]["type"] == "dishwasher_claim_downgraded"


def test_guard_downgrades_bedroom_without_bed() -> None:
    narration = [{
        "segment_id": "tl_001",
        "room_type": "Bedroom",
        "text": "卧室同样采用落地双开大窗，住起来特别舒坦。",
    }]
    timeline = {
        "segments": [{
            "id": "tl_001",
            "source_ids": ["seg_01"],
            "room_type": "Bedroom",
            "source": {"video_duration": 9.0},
            "duration_decision": {},
        }]
    }
    vkb = {"segments": [_vkb_segment("seg_01", "Bedroom", features=["large window", "closet"])]}

    out, _, audit = apply_tour_trust_guard(narration, timeline=timeline, vkb=vkb)

    assert out[0]["text"].startswith("这间房")
    assert "卧室" not in out[0]["text"]
    assert audit[0]["type"] == "bedroom_without_bed_downgraded"


def test_guard_pushes_approaching_bathroom_offset_and_flags_rewrite() -> None:
    narration = [{
        "segment_id": "tl_001",
        "room_type": "Bathroom",
        "text": "这间卫生间配备双台盆洗手台、大镜面与玻璃淋浴间。",
    }]
    timeline = {
        "segments": [{
            "id": "tl_001",
            "source_ids": ["seg_01"],
            "room_type": "Bathroom",
            "audio_offset": 4.0,
            "source": {"video_duration": 14.0},
            "narration": {"audio_duration": 8.0},
            "duration_decision": {"audio_duration": 8.0, "video_duration": 14.0},
        }]
    }
    vkb = {
        "segments": [
            _vkb_segment(
                "seg_01",
                "Bathroom",
                stage="approaching",
                start=88.0,
                visible=92.0,
                features=["dual sink vanity", "glass shower"],
            )
        ]
    }

    _, guarded, audit = apply_tour_trust_guard(narration, timeline=timeline, vkb=vkb)
    seg = guarded["segments"][0]

    assert seg["audio_offset"] > 6.0
    assert seg["duration_decision"]["needs_script_rewrite"] is True
    assert any(a["type"] == "private_room_offset_nudged" for a in audit)


def test_guard_waits_on_exiting_bedroom_before_bed_details() -> None:
    narration = [{
        "segment_id": "tl_001",
        "room_type": "Bedroom",
        "text": "步入卧室，床头灯带和落地窗让空间更温馨。",
    }]
    timeline = {
        "segments": [{
            "id": "tl_001",
            "source_ids": ["seg_01"],
            "room_type": "Bedroom",
            "audio_offset": 0.0,
            "source": {"video_duration": 8.0},
            "narration": {"audio_duration": 5.0},
            "duration_decision": {"audio_duration": 5.0, "video_duration": 8.0},
        }]
    }
    vkb = {
        "segments": [
            _vkb_segment(
                "seg_01",
                "Bedroom",
                stage="exiting",
                start=16.0,
                visible=16.0,
                features=["bed", "bedside lighting", "large window"],
            )
        ]
    }

    _, guarded, audit = apply_tour_trust_guard(narration, timeline=timeline, vkb=vkb)
    seg = guarded["segments"][0]

    assert seg["audio_offset"] >= 1.7
    assert seg["duration_decision"]["target_audio_duration"] < 6.0
    assert any(a["type"] == "private_room_offset_nudged" for a in audit)


def test_private_room_offset_nudge_is_idempotent() -> None:
    narration = [{
        "segment_id": "tl_001",
        "room_type": "Bedroom",
        "text": "这间卧室以弧形大窗为主。",
    }]
    timeline = {
        "segments": [{
            "id": "tl_001",
            "source_ids": ["seg_01"],
            "room_type": "Bedroom",
            "audio_offset": 0.0,
            "source": {"video_duration": 7.0},
            "duration_decision": {},
        }]
    }
    vkb = {"segments": [_vkb_segment("seg_01", "Bedroom", stage="exiting", features=["large window"])]}

    _, first_timeline, _ = apply_tour_trust_guard(narration, timeline=timeline, vkb=vkb)
    _, second_timeline, _ = apply_tour_trust_guard(narration, timeline=first_timeline, vkb=vkb)

    assert first_timeline["segments"][0]["audio_offset"] == 1.8
    assert second_timeline["segments"][0]["audio_offset"] == 1.8


def test_guard_applies_same_trust_rules_in_english() -> None:
    narration = [
        {
            "segment_id": "tl_001",
            "room_type": "Kitchen",
            "text": "The dishwasher door is open, with the racks clearly visible beside the sink.",
        },
        {
            "segment_id": "tl_002",
            "room_type": "Bedroom",
            "text": "Stepping into the bedroom, the large window makes it feel bright.",
        },
    ]
    timeline = {
        "segments": [
            {
                "id": "tl_001",
                "source_ids": ["seg_01"],
                "room_type": "Kitchen",
                "source": {"video_duration": 4.0},
                "duration_decision": {},
            },
            {
                "id": "tl_002",
                "source_ids": ["seg_02"],
                "room_type": "Bedroom",
                "audio_offset": 0.0,
                "source": {"video_duration": 8.0},
                "narration": {"audio_duration": 4.0},
                "duration_decision": {"audio_duration": 4.0, "video_duration": 8.0},
            },
        ]
    }
    vkb = {
        "segments": [
            _vkb_segment("seg_01", "Kitchen", features=["sink", "dishwasher"]),
            _vkb_segment(
                "seg_02",
                "Bedroom",
                stage="exiting",
                features=["large window", "closet"],
            ),
        ]
    }

    out, guarded, audit = apply_tour_trust_guard(
        narration,
        timeline=timeline,
        vkb=vkb,
        language="en",
    )

    assert "open" not in out[0]["text"].lower()
    assert "rack" not in out[0]["text"].lower()
    assert "integrated dishwasher" in out[0]["text"]
    assert out[1]["text"].startswith("This room")
    assert "bedroom" not in out[1]["text"].lower()
    assert guarded["segments"][1]["audio_offset"] >= 1.7
    assert {a["type"] for a in audit} >= {
        "dishwasher_claim_downgraded",
        "bedroom_without_bed_downgraded",
        "private_room_offset_nudged",
    }


def test_guard_rewrites_opening_view_intro_that_was_called_dining() -> None:
    narration = [{
        "segment_id": "tl_001",
        "room_type": "Dining Room",
        "text": "来到餐区，木纹餐桌配两把高脚椅，落地窗正对港湾海景。",
    }]
    timeline = {
        "segments": [{
            "id": "tl_001",
            "source_ids": ["seg_01"],
            "room_type": "Dining Room",
            "source": {"video_duration": 9.0},
            "duration_decision": {},
        }]
    }
    seg = _vkb_segment("seg_01", "Dining Room", start=0.0, features=["sea view", "harbor"])
    seg["knowledge"]["spaces"] = [
        {"type": "Living Room", "room_role": "glimpse", "features": ["seaview window"]},
        {"type": "Bedroom", "room_role": "glimpse", "features": ["sea view"]},
        {"type": "Dining Room", "room_role": "primary", "features": ["dining table"]},
    ]

    out, _, audit = apply_tour_trust_guard(narration, timeline=timeline, vkb={"segments": [seg]})

    assert out[0]["text"] == "先看这套房最重要的卖点，客厅和卧室都有开阔海景。"
    assert audit[0]["type"] == "opening_view_intro_rewritten"


def test_guard_splits_bathroom_tail_from_mixed_kitchen_service_segment() -> None:
    narration = [{
        "segment_id": "tl_001",
        "room_type": "Kitchen",
        "text": "厨房是功能核心，黑台面配燃气灶操作顺手。",
    }]
    timeline = {
        "segments": [{
            "id": "tl_001",
            "source_ids": ["seg_01"],
            "room_type": "Kitchen",
            "source": {"video_start": 45.0, "video_end": 54.89, "video_duration": 9.89},
            "duration_decision": {},
        }]
    }
    seg = _vkb_segment(
        "seg_01",
        "Kitchen",
        start=45.0,
        features=["black countertop", "gas cooktop", "window", "glass shower", "toilet"],
    )
    seg["room_visible_end"] = 50.75
    seg["raw"]["end_time"] = 54.89
    seg["knowledge"]["spaces"] = [
        {"type": "Kitchen", "room_role": "primary", "features": ["black countertop", "gas cooktop", "window"]},
        {"type": "Bathroom", "room_role": "secondary", "features": ["glass shower", "toilet"]},
    ]

    out, guarded, audit = apply_tour_trust_guard(narration, timeline=timeline, vkb={"segments": [seg]})

    assert "厨房先看黑台面和燃气灶" in out[0]["text"]
    assert "卫生间" not in out[0]["text"]
    assert out[1]["segment_id"] == "tl_001_bath"
    assert out[1]["room_type"] == "Bathroom"
    assert "卫生间" in out[1]["text"]
    assert "淋浴" in out[1]["text"]
    assert guarded["segments"][1]["room_type"] == "Bathroom"
    assert isinstance(guarded["segments"][1]["visual_plan"], dict)
    assert guarded["segments"][1]["source"]["video_duration"] <= 1.55
    assert guarded["segments"][1]["source"]["video_end"] < 52.0
    assert any(a["type"] == "mixed_service_tail_split" for a in audit)

    rechecked, _, recheck_audit = apply_tour_trust_guard(out, timeline=guarded, vkb={"segments": [seg]})
    assert "卫生间" not in rechecked[0]["text"]
    assert not any(a["type"] == "kitchen_service_tail_aligned" for a in recheck_audit)


def test_guard_replaces_unproven_bathtub_claim_with_visible_fixtures() -> None:
    narration = [{
        "segment_id": "tl_001",
        "room_type": "Bathroom",
        "text": "卫生间配有浴缸和马桶。",
    }]
    timeline = {
        "segments": [{
            "id": "tl_001",
            "source_ids": ["seg_01"],
            "room_type": "Bathroom",
            "source": {"video_start": 49.6, "video_end": 51.15, "video_duration": 1.55},
            "duration_decision": {},
        }]
    }
    seg = _vkb_segment("seg_01", "Bathroom", features=["glass shower", "toilet"])
    seg["knowledge"]["spaces"] = [
        {"type": "Bathroom", "room_role": "primary", "features": ["glass shower", "toilet"]},
    ]

    out, _, audit = apply_tour_trust_guard(narration, timeline=timeline, vkb={"segments": [seg]})

    assert out[0]["text"] == "卫生间带淋浴、马桶。"
    assert any(a["type"] == "unsupported_bathroom_fixture_downgraded" for a in audit)
