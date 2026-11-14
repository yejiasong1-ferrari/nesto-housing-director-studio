"""One shot, one subject — and no two rooms sold with the same three phrases.

Every input line here was spoken in a shipped v3.4 final cut (properties 4 and
7); the assertions describe what an agent standing in that room would say.
"""

from backend.agents.script.pipeline.marketing_enricher import (
    dedupe_generic_atmosphere,
    enforce_single_room_subject,
    sanitize_timeline_narration,
    sanitize_unverified_room_ranks,
    strip_bathroom_house_style,
)


def test_bathroom_line_does_not_sell_the_bedroom_next_door() -> None:
    out = enforce_single_room_subject(
        "这是卫生间，配备壁挂式马桶、玻璃淋浴房与悬浮式洗手台，旁边卧室可见大床与落地窗景。",
        room_type="Bathroom",
    )
    assert "卧室" not in out
    assert "大床" not in out
    assert "壁挂式马桶" in out
    assert out.endswith("。")


def test_bedroom_line_does_not_open_in_the_hallway() -> None:
    out = enforce_single_room_subject(
        "现在步入走廊，深色木地板通铺到底，两侧是几扇带金属拉手的房门；"
        "旁边这间卧室同样铺设深色地板，整体连贯统一。",
        room_type="Bedroom",
    )
    assert "走廊" not in out
    assert "这间卧室" in out
    # The adjacency framing goes with it — we are inside this bedroom.
    assert "旁边这间卧室" not in out


def test_closing_line_settles_inside_the_living_room() -> None:
    out = enforce_single_room_subject(
        "现在站在走廊中，深色木地板向前延伸——前方就是客厅，整面落地窗将自然光引入室内。",
        room_type="Living Room",
    )
    assert "走廊" not in out
    assert "客厅" in out
    assert "落地窗" in out


def test_access_to_another_room_is_a_feature_not_a_detour() -> None:
    out = enforce_single_room_subject(
        "步入这间卧室，墙边是双滑门衣柜，落地推拉玻璃门直通阳台。",
        room_type="Bedroom",
    )
    assert "直通阳台" in out
    assert "双滑门衣柜" in out


def test_own_room_named_many_times_is_untouched() -> None:
    text = "转过来是厨房，深灰橱柜配石英台面，嵌入式烤箱与灶台一体，下厨很顺手。"
    assert enforce_single_room_subject(text, room_type="Kitchen") == text


def test_unplaceable_room_keeps_its_line() -> None:
    text = "窗外是开阔的城市天际线，视野毫无遮挡。"
    assert enforce_single_room_subject(text, room_type="Unknown") == text


def test_living_room_does_not_claim_the_laundry_it_is_not_in() -> None:
    out = enforce_single_room_subject(
        "客厅里橙色沙发搭配条纹地毯，角落整合了洗衣区，叠放式洗衣机烘干机使用省心。",
        room_type="Living Room",
    )
    assert "洗衣区" not in out
    assert "橙色沙发" in out


def test_balcony_does_not_look_back_and_sell_the_living_room() -> None:
    out = enforce_single_room_subject(
        "推开落地玻璃门就是阳台，两张户外椅正对城市景观；回看客厅，采光充足又温馨。",
        room_type="Balcony",
    )
    assert "客厅" not in out
    assert "户外椅" in out


def test_balcony_access_does_not_name_the_living_room() -> None:
    out = enforce_single_room_subject(
        "站在阳台上，推拉门直通客厅，灰色地砖从阳台延伸至室内。",
        room_type="Balcony",
    )
    assert "客厅" not in out
    assert "地砖" in out


def test_living_room_does_not_claim_laundry_closet_or_stack() -> None:
    out = enforce_single_room_subject(
        "客厅里橙色沙发搭配波浪纹地毯，洗烘区嵌入角落省空间又安静。",
        room_type="Living Room",
    )
    assert "洗烘" not in out
    assert "橙色沙发" in out


def test_bathroom_does_not_sell_the_laundry_stack() -> None:
    out = enforce_single_room_subject(
        "墙面悬挑马桶、独立淋浴间一应俱全；另一侧叠放式洗衣机与烘干机嵌入得恰到好处。",
        room_type="Bathroom",
    )
    assert "洗衣" not in out and "烘干" not in out
    assert "马桶" in out


def test_mixed_close_does_not_sell_the_living_room_from_the_hall() -> None:
    out = enforce_single_room_subject(
        "客厅通透明亮，整面落地窗引入充足自然光，深色木地板与白墙形成干净对比。",
        room_type="Mixed Private Area",
    )
    assert "客厅" not in out


def test_bedroom_does_not_sell_the_kitchen_fridge() -> None:
    out = enforce_single_room_subject(
        "进入卧室，全屋延续深色实木地板与白墙；背景中嵌入式冰箱与整体风格协调。",
        room_type="Bedroom",
    )
    assert "冰箱" not in out
    assert "卧室" in out


def test_mixed_close_does_not_keep_balcony_access() -> None:
    out = enforce_single_room_subject(
        "落地玻璃门直通阳台，大窗引入充足自然光，这里是拥抱城市风景的私享空间。",
        room_type="Mixed Private Area",
    )
    assert "阳台" not in out
    assert "直通" not in out


def test_brochure_phrases_are_stripped() -> None:
    out = sanitize_timeline_narration(
        "厨房是核心区域：嵌入式冰箱微开即见层架，下厨高效顺手。",
        room_type="Kitchen",
    )
    assert "核心区域" not in out
    assert "微开即见" not in out
    assert "高效顺手" not in out
    assert "冰箱" in out or "厨房" in out


def test_required_space_survives_subject_check() -> None:
    out = enforce_single_room_subject(
        "客厅通透敞亮，转角处是独立洗衣房，叠放洗烘机一应俱全。",
        room_type="Living Room",
        allowed_rooms=("Laundry Room",),
    )
    assert "洗衣房" in out


def test_room_counting_is_never_spoken() -> None:
    assert "第二间" not in sanitize_unverified_room_ranks("我们来到第二间卫生间，设施齐全。")
    assert "另一间" not in sanitize_unverified_room_ranks("这边是另一间卧室，采光不错。")
    assert "卫生间" in sanitize_unverified_room_ranks("我们来到第二间卫生间，设施齐全。")


def test_timeline_gate_applies_both_rank_and_subject_rules() -> None:
    out = sanitize_timeline_narration(
        "这是次卫生间，壁挂马桶与双台盆，旁边卧室摆着一张大床。",
        room_type="Bathroom",
    )
    assert "次卫" not in out and "生间生间" not in out
    assert "大床" not in out
    assert "双台盆" in out


def test_late_room_cannot_be_sold_on_house_style_alone() -> None:
    segments = [
        {"segment_id": "tl_001", "text": "步入这间卧室，深色木地板搭配白墙，大窗采光充足。"},
        {"segment_id": "tl_002", "text": "这间卧室墙边设有双滑门衣柜，深色木地板延续全屋。"},
        {"segment_id": "tl_003", "text": "这间卧室同样铺深色木地板，白墙搭配大窗，城市景观一览无余。"},
        {"segment_id": "tl_004", "text": "这是卫生间，壁挂马桶与玻璃淋浴房，白墙搭配深色地板。"},
        {"segment_id": "tl_005", "text": "这间卧室宽敞，深色木地板搭配白墙，大窗采光充足。"},
        {"segment_id": "tl_006", "text": "客厅通透敞亮，落地窗对着城市景观。"},
    ]
    out = dedupe_generic_atmosphere(segments)
    # Evidence a buyer can only see in that room always survives.
    assert "衣柜" in out[1]["text"]
    assert "壁挂马桶" in out[3]["text"]
    # By the fifth room the shared house style stops being a room's whole line.
    assert "深色木地板搭配白墙" not in out[4]["text"]
    # …but the room the camera is in is never dropped.
    assert "这间卧室" in out[4]["text"]
    assert "卫生间" in out[3]["text"]


def test_dedupe_never_thins_the_opening() -> None:
    style = "深色木地板搭配白墙，大窗采光充足"
    segments = [
        {"segment_id": f"tl_{i:03d}", "text": f"这间卧室{style}。"} for i in range(1, 7)
    ]
    segments[-1]["text"] = f"客厅整面落地窗对着城市景观，{style}。"
    out = dedupe_generic_atmosphere(segments)
    assert out[0]["text"] == segments[0]["text"]
    assert "这间卧室" in out[4]["text"]
    assert out[-1]["text"].strip()


def test_dedupe_never_leaves_a_segment_silent() -> None:
    segments = [
        {"segment_id": "tl_001", "text": "深色木地板搭配白墙。"},
        {"segment_id": "tl_002", "text": "深色木地板搭配白墙。"},
        {"segment_id": "tl_003", "text": "深色木地板搭配白墙。"},
        {"segment_id": "tl_004", "text": "深色木地板搭配白墙。"},
    ]
    out = dedupe_generic_atmosphere(segments)
    assert all(s["text"].strip() for s in out)


def test_dedupe_keeps_english_untouched() -> None:
    segments = [{"segment_id": "tl_001", "text": "Dark floors, white walls, big windows."}]
    assert dedupe_generic_atmosphere(segments, language="en") == segments


def test_bathroom_keeps_fixtures_and_drops_house_style() -> None:
    # Spoken in 7-v42 over a bathroom that has a vanity, not a wood floor
    # or a floor-to-ceiling window.
    text = (
        "接着是卫生间，深色木地板延续整体风格，白墙干净清爽；"
        "悬空洗手台搭配嵌入式水槽与壁挂镜，落地窗引入自然光，"
        "空间明亮通透，使用体验从容舒适。"
    )
    out = strip_bathroom_house_style(text, room_type="Bathroom")
    assert "洗手台" in out and "壁挂镜" in out
    assert "卫生间" in out
    assert "木地板" not in out
    assert "白墙" not in out
    assert "落地窗" not in out
    assert "自然光" not in out
    assert "明亮通透" not in out
    assert "从容舒适" not in out


def test_sanitize_strips_bathroom_house_style() -> None:
    out = sanitize_timeline_narration(
        "接着是卫生间，深色木地板延续整体风格，白墙干净清爽；"
        "悬空洗手台搭配嵌入式水槽与壁挂镜，落地窗引入自然光。",
        room_type="Bathroom",
    )
    assert "洗手台" in out
    assert "木地板" not in out
    assert "落地窗" not in out


def test_house_style_is_not_repeated_after_the_first_room() -> None:
    segments = [
        {"segment_id": "tl_001", "room_type": "Living Room",
         "text": "来到客厅，落地大窗引入充足自然光，深色实木地板沉稳耐看。"},
        {"segment_id": "tl_002", "room_type": "Bedroom",
         "text": "进入卧室，深色实木地板通铺全屋，白墙与衣柜简洁利落。"},
        {"segment_id": "tl_003", "room_type": "Bathroom",
         "text": "接着是卫生间，深色木地板延续整体风格，悬空洗手台搭配壁挂镜。"},
    ]
    out = dedupe_generic_atmosphere(segments)
    assert "落地大窗" in out[0]["text"]
    assert "衣柜" in out[1]["text"]
    assert "深色实木地板通铺全屋" not in out[1]["text"]
    assert "洗手台" in out[2]["text"]
    assert "木地板" not in out[2]["text"]
