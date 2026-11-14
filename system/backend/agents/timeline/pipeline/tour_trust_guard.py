"""Tour Trust Guard: keep narration anchored to what the buyer can point at.

Runs after timeline narration polish and before Voice/TTS. It is deliberately
conservative: only downgrades phrases that create obvious walkthrough trust
breaks, and nudges delayed-entry rooms later rather than letting downstream
timing pull speech back into the hallway.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

PRIVATE_APPROACH_ROOMS = {"Bathroom", "Bedroom", "Laundry Room"}
BATHROOM_EXTRA_WAIT = 2.4
BEDROOM_EXITING_WAIT = 1.8
AUDIO_TAIL_PAD = 0.40
SERVICE_TAIL_MIN_DURATION = 1.0
SERVICE_TAIL_MAX_DURATION = 1.55
SERVICE_TAIL_LEAD_IN = 1.15


def apply_tour_trust_guard(
    narration_segments: list[dict[str, Any]],
    *,
    timeline: dict[str, Any],
    vkb: dict[str, Any],
    language: str = "zh",
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Return guarded narration + timeline + audit entries."""
    lang = (language or "en").lower()
    if lang not in {"zh", "en"}:
        lang = "en"

    guarded_segments = [dict(s) for s in narration_segments]
    guarded_timeline = copy.deepcopy(timeline or {})
    vkb_by_id = {str(s.get("segment_id") or ""): s for s in (vkb or {}).get("segments", [])}
    tl_by_id = {
        str(s.get("id") or "").split("[", 1)[0]: s
        for s in guarded_timeline.get("segments", [])
    }
    timeline_ids = {str(s.get("id") or "") for s in guarded_timeline.get("segments", [])}
    audit: list[dict[str, Any]] = []

    for item in guarded_segments:
        sid = str(item.get("segment_id") or "")
        tl = tl_by_id.get(sid)
        if not tl:
            continue
        source_ids = [str(x) for x in (tl.get("source_ids") or item.get("source_ids") or [])]
        sources = [vkb_by_id[s] for s in source_ids if s in vkb_by_id]
        room_type = str(item.get("room_type") or tl.get("room_type") or "")
        text = str(item.get("text") or "")
        new_text = text

        if _is_opening_view_intro(sources, room_type, text):
            replacement = _opening_view_intro_text(sources, language=lang)
            if replacement and replacement != new_text:
                new_text = replacement
                audit.append({"segment_id": sid, "type": "opening_view_intro_rewritten"})

        if room_type == "Kitchen":
            cleaned = _degrade_unproven_dishwasher_claim(new_text, sources, language=lang)
            if cleaned != new_text:
                new_text = cleaned
                audit.append({"segment_id": sid, "type": "dishwasher_claim_downgraded"})
            if f"{sid}_bath" not in timeline_ids:
                cleaned = _align_kitchen_service_tail(new_text, sources, language=lang)
                if cleaned != new_text:
                    new_text = cleaned
                    audit.append({"segment_id": sid, "type": "kitchen_service_tail_aligned"})

        if _canonical_room(room_type) == "Bathroom":
            cleaned = _degrade_unsupported_bathroom_fixture(new_text, sources, language=lang)
            if cleaned != new_text:
                new_text = cleaned
                audit.append({"segment_id": sid, "type": "unsupported_bathroom_fixture_downgraded"})

        if _canonical_room(room_type) == "Bedroom" and not _has_bed_evidence(sources):
            cleaned = _degrade_bedroom_without_bed(new_text, sources, language=lang)
            if cleaned != new_text:
                new_text = cleaned
                audit.append({"segment_id": sid, "type": "bedroom_without_bed_downgraded"})

        if _canonical_room(room_type) in PRIVATE_APPROACH_ROOMS:
            before = float(tl.get("audio_offset") or 0.0)
            after = _safer_private_room_offset(tl, sources, room_type)
            if after > before + 0.05:
                tl["audio_offset"] = round(after, 3)
                dur = tl.setdefault("duration_decision", {})
                target_audio = _target_audio_duration(tl, after)
                dur["target_audio_duration"] = round(target_audio, 2)
                narr = tl.get("narration") or {}
                audio_dur = float(dur.get("audio_duration") or narr.get("audio_duration") or 0.0)
                if audio_dur > target_audio + 0.35:
                    dur["strategy"] = "flag_rewrite"
                    dur["needs_script_rewrite"] = True
                    dur["extension_factor"] = 1.0
                audit.append({
                    "segment_id": sid,
                    "type": "private_room_offset_nudged",
                    "from": round(before, 3),
                    "to": round(after, 3),
                })

        item["text"] = _tidy_text(new_text, language=lang)

    guarded_segments, guarded_timeline, split_audit = _split_mixed_service_tails(
        guarded_segments,
        guarded_timeline,
        vkb_by_id,
        language=lang,
    )
    audit.extend(split_audit)

    if audit:
        logger.info("TourTrustGuard applied %d fixes: %s", len(audit), audit)
    guarded_timeline["tour_trust_guard"] = {"applied": audit}
    return guarded_segments, guarded_timeline, audit


def _canonical_room(room: str) -> str:
    return {
        "Primary Bedroom": "Bedroom",
        "Secondary Bedroom": "Bedroom",
        "Guest Bedroom": "Bedroom",
        "Bedroom Area": "Bedroom",
        "Laundry": "Laundry Room",
        "Laundry Area": "Laundry Room",
    }.get((room or "").strip(), (room or "").strip())


def _blob(parts: list[Any]) -> str:
    return " ".join(str(p).lower() for p in parts if p)


def _source_blob(sources: list[dict[str, Any]]) -> str:
    bits: list[Any] = []
    for src in sources:
        k = src.get("knowledge") or {}
        bits.extend(k.get("selling_points") or [])
        bits.extend(k.get("furniture") or [])
        bits.extend(k.get("appliances") or [])
        for sp in k.get("spaces") or []:
            bits.extend(sp.get("features") or [])
    return _blob(bits)


def _has_space(sources: list[dict[str, Any]], room: str, role: str | None = None) -> bool:
    for src in sources:
        for sp in (src.get("knowledge") or {}).get("spaces") or []:
            if (sp.get("type") or "") != room:
                continue
            if role and (sp.get("room_role") or "") != role:
                continue
            return True
    return False


def _is_opening_view_intro(sources: list[dict[str, Any]], room_type: str, text: str) -> bool:
    if not sources:
        return False
    earliest = min(float((s.get("raw") or {}).get("start_time") or 0.0) for s in sources)
    if earliest > 1.0:
        return False
    if _canonical_room(room_type) not in {"Dining Room", "Living Room", ""}:
        return False
    blob = _source_blob(sources)
    has_view = any(t in blob for t in ("sea view", "seaview", "harbor", "海景", "港湾"))
    cross_room_view = _has_space(sources, "Living Room") and _has_space(sources, "Bedroom")
    dining_claim = any(t in (text or "") for t in ("餐区", "餐厅", "dining"))
    return bool(has_view and cross_room_view and dining_claim)


def _opening_view_intro_text(sources: list[dict[str, Any]], *, language: str) -> str:
    if language == "en":
        return "First, the key selling point: both the living area and bedroom enjoy an open sea view."
    return "先看这套房最重要的卖点，客厅和卧室都有开阔海景。"


def _align_kitchen_service_tail(
    text: str,
    sources: list[dict[str, Any]],
    *,
    language: str,
) -> str:
    """Make kitchen lines follow the actual service-room move.

    If one source segment contains a kitchen as primary and a bathroom as a
    real secondary room, a kitchen-only line leaves the bathroom ending mute.
    If the kitchen evidence is only a window/view, avoid selling fixtures.
    """
    if not text:
        return text
    blob = _source_blob(sources)
    lower = text.lower()
    has_bath_tail = _has_space(sources, "Bathroom")
    mentions_bath = any(t in lower or t in text for t in ("bathroom", "shower", "toilet", "卫生间", "淋浴", "马桶"))
    has_cooktop = any(t in blob for t in ("cooktop", "stove", "gas", "燃气灶", "灶"))
    has_counter = any(t in blob for t in ("counter", "台面", "black countertop"))
    has_window = any(t in blob for t in ("window", "natural light", "窗", "采光", "海景", "harbor"))

    if has_bath_tail and not mentions_bath:
        if language == "en":
            kitchen = "The kitchen first shows the dark counter and gas cooktop" if has_cooktop else "The kitchen keeps the service run compact"
            bath = _bathroom_tail_phrase_en(sources)
            return f"{kitchen}; the shot then carries through to the bathroom with {bath}."
        kitchen = "厨房先看黑台面和燃气灶" if has_cooktop or has_counter else "厨房动线紧凑"
        window = "，窗边也保留自然采光" if has_window else ""
        bath = _bathroom_tail_phrase_zh(sources)
        return f"{kitchen}{window}；最后带到卫生间的{bath}。"

    fixture_claim = any(t in text or t in lower for t in ("燃气灶", "灶台", "台面", "cooktop", "counter", "stove"))
    if fixture_claim and not (has_cooktop or has_counter) and has_window:
        if language == "en":
            return "The kitchen window brings in natural light, keeping the service area brighter."
        return "厨房窗边保留自然采光，服务区更明亮。"
    return text


def _bathroom_tail_phrase_zh(sources: list[dict[str, Any]]) -> str:
    blob = _source_blob(sources)
    parts = []
    if any(t in blob for t in ("shower", "淋浴", "花洒")):
        parts.append("淋浴")
    if any(t in blob for t in ("toilet", "马桶", "坐便")):
        parts.append("马桶")
    if any(t in blob for t in ("vanity", "sink", "台盆", "洗手台")):
        parts.append("洗手台")
    return "、".join(parts[:2] or ["基础卫浴配置"])


def _bathroom_tail_phrase_en(sources: list[dict[str, Any]]) -> str:
    blob = _source_blob(sources)
    parts = []
    if "shower" in blob:
        parts.append("a glass shower")
    if "toilet" in blob:
        parts.append("a toilet")
    if "vanity" in blob or "sink" in blob:
        parts.append("a vanity")
    return " and ".join(parts[:2] or ["practical fixtures"])


def _split_mixed_service_tails(
    narration_segments: list[dict[str, Any]],
    timeline: dict[str, Any],
    vkb_by_id: dict[str, dict[str, Any]],
    *,
    language: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Split Kitchen->Bathroom tails so bathroom speech lands on bathroom pixels."""
    tl_segments = timeline.get("segments") or []
    if not tl_segments or not narration_segments:
        return narration_segments, timeline, []

    narration_by_id = {
        str(s.get("segment_id") or ""): s
        for s in narration_segments
    }
    new_timeline_segments: list[dict[str, Any]] = []
    new_narration_segments: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for tl in tl_segments:
        sid = str(tl.get("id") or "").split("[", 1)[0]
        narration = narration_by_id.get(sid)
        source_ids = [str(x) for x in (tl.get("source_ids") or [])]
        sources = [vkb_by_id[s] for s in source_ids if s in vkb_by_id]
        split = _build_service_tail_split(tl, narration, sources, source_ids, language=language)

        if split:
            kitchen_tl, bathroom_tl, kitchen_narr, bathroom_narr = split
            new_timeline_segments.extend([kitchen_tl, bathroom_tl])
            if narration:
                new_narration_segments.extend([kitchen_narr, bathroom_narr])
            audit.append({
                "segment_id": sid,
                "type": "mixed_service_tail_split",
                "bathroom_segment_id": bathroom_tl.get("id"),
            })
            continue

        new_timeline_segments.append(tl)
        if narration:
            new_narration_segments.append(narration)

    if not audit:
        return narration_segments, timeline, []

    timeline["segments"] = _retime_timeline_segments(new_timeline_segments)
    timeline["segment_count"] = len(timeline["segments"])
    timeline["total_duration"] = round(sum(float(s.get("duration") or 0.0) for s in timeline["segments"]), 3)
    retimed_by_id = {str(s.get("id") or ""): s for s in timeline["segments"]}
    for item in new_narration_segments:
        seg_id = str(item.get("segment_id") or "")
        tl = retimed_by_id.get(seg_id)
        if not tl:
            continue
        item["scene_id"] = seg_id
        item["start_time"] = tl.get("timeline_start")
        item["end_time"] = tl.get("timeline_end")
        item["scene_duration"] = tl.get("duration")
    return new_narration_segments, timeline, audit


def _build_service_tail_split(
    tl: dict[str, Any],
    narration: dict[str, Any] | None,
    sources: list[dict[str, Any]],
    source_ids: list[str],
    *,
    language: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    if (tl.get("room_type") or "") != "Kitchen" or not narration or len(sources) != 1:
        return None
    if not _has_space(sources, "Bathroom"):
        return None

    src = sources[0]
    raw = src.get("raw") or {}
    source_start = _to_float((tl.get("source") or {}).get("video_start"), raw.get("start_time"))
    source_end = _to_float((tl.get("source") or {}).get("video_end"), raw.get("end_time"))
    if source_end <= source_start:
        source_end = source_start + _to_float((tl.get("source") or {}).get("video_duration"), 0.0)
    if source_end - source_start < 5.0:
        return None

    visible_end = _to_float(src.get("room_visible_end"), source_start + (source_end - source_start) * 0.72)
    bath_start = max(source_start + 1.0, min(visible_end - SERVICE_TAIL_LEAD_IN, source_end - SERVICE_TAIL_MIN_DURATION))
    bath_end = min(source_end, bath_start + SERVICE_TAIL_MAX_DURATION)
    if bath_end - bath_start < SERVICE_TAIL_MIN_DURATION:
        return None
    if bath_start - source_start < 2.4:
        return None

    kitchen_tl = copy.deepcopy(tl)
    bathroom_tl = copy.deepcopy(tl)
    bathroom_id = _unique_tail_id(str(tl.get("id") or "tl_service"), "bath")

    _set_source_window(kitchen_tl, source_start, bath_start)
    kitchen_tl["room_type"] = "Kitchen"
    kitchen_tl["visual_plan"] = _service_split_visual_plan(tl.get("visual_plan"), "Kitchen", language=language)
    kitchen_tl["narration"] = {}
    kitchen_tl["audio_offset"] = min(float(kitchen_tl.get("audio_offset") or 0.0), 0.2)
    _reset_duration_decision(kitchen_tl)

    _set_source_window(bathroom_tl, bath_start, bath_end)
    bathroom_tl["id"] = bathroom_id
    bathroom_tl["room_type"] = "Bathroom"
    bathroom_tl["role"] = "SUPPORT"
    bathroom_tl["room_role"] = "support"
    bathroom_tl["importance_score"] = min(float(bathroom_tl.get("importance_score") or 0.6), 0.7)
    bathroom_tl["importance"] = min(float(bathroom_tl.get("importance") or 0.6), 0.7)
    bathroom_tl["visual_plan"] = _service_split_visual_plan(tl.get("visual_plan"), "Bathroom", language=language)
    bathroom_tl["audio_offset"] = 0.0
    _reset_duration_decision(bathroom_tl)

    kitchen_narr = dict(narration)
    kitchen_narr.pop("tts_text", None)
    kitchen_narr["text"] = _tidy_text(_kitchen_service_split_text(sources, language=language), language=language)
    kitchen_narr["room_type"] = "Kitchen"
    kitchen_narr["source_ids"] = source_ids

    bathroom_narr = dict(narration)
    bathroom_narr.pop("tts_text", None)
    bathroom_narr["segment_id"] = bathroom_id
    bathroom_narr["scene_id"] = bathroom_id
    bathroom_narr["room_type"] = "Bathroom"
    bathroom_narr["role"] = "SUPPORT"
    bathroom_narr["importance"] = min(float(bathroom_narr.get("importance") or 0.6), 0.7)
    bathroom_narr["source_ids"] = source_ids
    bathroom_narr["text"] = _tidy_text(_bathroom_service_split_text(sources, language=language), language=language)
    return kitchen_tl, bathroom_tl, kitchen_narr, bathroom_narr


def _to_float(value: Any, fallback: Any = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(fallback)
        except (TypeError, ValueError):
            return 0.0


def _set_source_window(tl: dict[str, Any], start: float, end: float) -> None:
    source = tl.setdefault("source", {})
    duration = max(0.0, end - start)
    source["video_start"] = round(start, 3)
    source["video_end"] = round(end, 3)
    source["video_duration"] = round(duration, 3)
    tl["duration"] = round(duration, 3)
    tl["room_visible_end"] = round(end, 3)


def _reset_duration_decision(tl: dict[str, Any]) -> None:
    duration = float(tl.get("duration") or 0.0)
    decision = tl.setdefault("duration_decision", {})
    decision["editing_window"] = round(duration, 3)
    decision["target_audio_duration"] = round(max(0.0, duration - AUDIO_TAIL_PAD), 2)
    decision["extension_factor"] = 1.0
    decision["strategy"] = "split_service_tail"
    decision["needs_script_rewrite"] = True


def _unique_tail_id(base: str, suffix: str) -> str:
    clean = base.split("[", 1)[0].strip() or "tl_service"
    return f"{clean}_{suffix}"


def _service_split_visual_plan(original: Any, room: str, *, language: str) -> dict[str, Any]:
    plan = dict(original) if isinstance(original, dict) else {}
    plan.setdefault("story_phase", "discovery")
    plan.setdefault("pace", "medium")
    if room == "Bathroom":
        plan["focus_elements"] = ["glass shower", "toilet", "bathroom fixtures"]
        plan["cinematic_intent"] = "hold_on_visible_bathroom_fixtures_only"
        plan["guardrail"] = "Do not use title cards, black frames, or hallway frames for this bathroom beat."
        return plan
    plan["focus_elements"] = ["kitchen worktop", "cabinets", "gas cooktop", "kitchen window"]
    plan["cinematic_intent"] = "hold_on_visible_kitchen_fixtures_only"
    plan["guardrail"] = "Keep this beat on the kitchen worktop, cabinets, cooktop, and window only."
    return plan


def _kitchen_service_split_text(sources: list[dict[str, Any]], *, language: str) -> str:
    blob = _source_blob(sources)
    has_cooktop = any(t in blob for t in ("cooktop", "stove", "gas", "燃气灶", "灶"))
    has_counter = any(t in blob for t in ("counter", "台面", "black countertop"))
    has_window = any(t in blob for t in ("window", "natural light", "窗", "采光", "海景", "harbor"))
    if language == "en":
        if has_cooktop or has_counter:
            suffix = ", with natural light by the window" if has_window else ""
            return f"The kitchen keeps the dark worktop and gas cooktop in view{suffix}."
        return "The kitchen service run stays compact and bright."
    if has_cooktop or has_counter:
        suffix = "，窗边也有自然采光" if has_window else ""
        return f"厨房先看黑台面和燃气灶{suffix}。"
    return "厨房服务区紧凑，采光也比较自然。"


def _bathroom_service_split_text(sources: list[dict[str, Any]], *, language: str) -> str:
    if language == "en":
        return f"The bathroom includes {_bathroom_tail_phrase_en(sources)}."
    return f"卫生间带{_bathroom_tail_phrase_zh(sources)}。"


def _degrade_unsupported_bathroom_fixture(
    text: str,
    sources: list[dict[str, Any]],
    *,
    language: str,
) -> str:
    if not text:
        return text
    lower = text.lower()
    mentions_tub = any(t in text or t in lower for t in ("浴缸", "bathtub", "bath tub", "tub"))
    if not mentions_tub:
        return text
    blob = _source_blob(sources)
    has_tub = any(t in blob for t in ("bathtub", "bath tub", "浴缸"))
    if has_tub:
        return text
    has_shower = any(t in blob for t in ("shower", "淋浴", "花洒"))
    has_toilet = any(t in blob for t in ("toilet", "马桶", "坐便"))
    if language == "en":
        if has_shower or has_toilet:
            return f"The bathroom includes {_bathroom_tail_phrase_en(sources)}."
        return "The bathroom includes practical daily fixtures."
    if has_shower or has_toilet:
        return f"卫生间带{_bathroom_tail_phrase_zh(sources)}。"
    return "卫生间配备基础卫浴功能。"


def _retime_timeline_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = 0.0
    for seg in segments:
        duration = float(seg.get("duration") or (seg.get("source") or {}).get("video_duration") or 0.0)
        seg["timeline_start"] = round(cursor, 3)
        cursor += duration
        seg["timeline_end"] = round(cursor, 3)
        seg["duration"] = round(duration, 3)
    return segments


def _degrade_unproven_dishwasher_claim(
    text: str,
    sources: list[dict[str, Any]],
    *,
    language: str,
) -> str:
    lower = (text or "").lower()
    mentions = "洗碗机" in text or "dishwasher" in lower
    if not mentions:
        return text
    # Even when Vision has a dishwasher, "door open / racks visible" is too
    # fragile unless the exact visual is the subject. Say the durable fact.
    risky = (
        "门已打开", "打开", "碗篮", "内部", "清晰可见", "拉开",
        "open door", "door open", "opened", "rack", "racks", "basket",
        "baskets", "interior", "inside", "clearly visible", "visible inside",
    )
    if not any(token in text or token in lower for token in risky):
        return text
    blob = _source_blob(sources)
    sink_nearby = "sink" in blob or "水槽" in text or "sink" in lower
    if language == "en":
        if sink_nearby:
            return "There is an integrated dishwasher beside the sink, keeping the kitchen workflow compact."
        return "The kitchen includes an integrated dishwasher for easier daily cleanup."
    if sink_nearby:
        return "水槽旁配置嵌入式洗碗机位，厨房动线紧凑。"
    return "厨房配置嵌入式洗碗机，日常使用更省心。"


def _has_bed_evidence(sources: list[dict[str, Any]]) -> bool:
    blob = _source_blob(sources)
    bed_tokens = (" bed", "bed ", "bed with", "double bed", "床", "床品", "床头")
    return any(token in f" {blob} " for token in bed_tokens)


def _has_closet_evidence(sources: list[dict[str, Any]]) -> bool:
    blob = _source_blob(sources)
    return any(token in blob for token in ("closet", "wardrobe", "衣柜", "hanging rod", "推拉门"))


def _degrade_bedroom_without_bed(
    text: str,
    sources: list[dict[str, Any]],
    *,
    language: str,
) -> str:
    if not text:
        return text
    has_closet = _has_closet_evidence(sources)
    if language == "en":
        if has_closet:
            return "This room has a large window and built-in closet, so the light and storage both feel practical."
        return "This room is mainly about the large window and city outlook, giving the space a bright, open feel."
    if has_closet:
        return "这间房带大窗和内嵌衣柜，采光与收纳都比较实用。"
    return "这间房以大窗和城市视野为主，空间明亮通透。"


def _safer_private_room_offset(
    tl: dict[str, Any],
    sources: list[dict[str, Any]],
    room_type: str,
) -> float:
    source = tl.get("source") or {}
    video_dur = float(source.get("video_duration") or 0.0)
    current = float(tl.get("audio_offset") or 0.0)
    if video_dur <= 0:
        return current

    stages = {str(s.get("room_stage") or "") for s in sources}
    offsets = []
    for s in sources:
        raw = s.get("raw") or {}
        start = float(raw.get("start_time") or 0.0)
        visible = float(s.get("room_visible_start") or start)
        offsets.append(max(0.0, visible - start))
    max_source_offset = max(offsets or [0.0])
    wanted = max_source_offset

    if _canonical_room(room_type) == "Bathroom" and (
        "approaching" in stages or wanted >= 3.6
    ):
        wanted += BATHROOM_EXTRA_WAIT
    elif _canonical_room(room_type) == "Bedroom" and "exiting" in stages:
        # A bedroom classified as "exiting" often starts on a door jamb or
        # hallway edge. Let the frame settle on the bed/window before selling
        # bed-specific details.
        wanted += BEDROOM_EXITING_WAIT

    # Leave enough room for a short, useful phrase. If that is impossible, keep
    # the current offset and let the line stay short.
    target = min(wanted, max(0.0, video_dur - 2.6))
    return max(current, target)


def _target_audio_duration(tl: dict[str, Any], offset: float) -> float:
    source = tl.get("source") or {}
    video_dur = float(source.get("video_duration") or 0.0)
    return max(0.0, video_dur - max(0.0, offset) - AUDIO_TAIL_PAD)


def _tidy_text(text: str, *, language: str) -> str:
    out = text or ""
    if language == "zh":
        out = re.sub(r"[，、]{2,}", "，", out)
        out = re.sub(r"^[，、；;：:\s]+", "", out)
        out = re.sub(r"[，、；;]+(?=[。！？]|$)", "", out)
        return out.strip()
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"^[,;:\s]+", "", out)
    out = re.sub(r"[,;]+(?=[.!?]|$)", "", out)
    return out.strip()
