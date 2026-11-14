"""Rule-based marketing enrichment for weak / incomplete narration lines.

Guarantees the Script Agent ships property information even when the LLM
returns mood-only or truncated sentences.
"""

from __future__ import annotations

import re

from backend.schemas.vision_schema import VKBSegment, VisionKnowledgeBase
from backend.workflows.room_naming import narration_label

_EMPTY_ZH = re.compile(
    r"(以光为魂|以简为美|静诉温润|诗意日常|恰如其分)"
)
_BENEFIT_CUES_ZH = (
    "便利", "舒适", "实用", "采光", "收纳", "开阔", "提升", "适合", "方便",
    "日常", "居住", "使用",
)
_INCOMPLETE_END_ZH = ("里。", "中。", "下。", "的。", "与。", "和。", "间。")

# Speakable space → cues that prove the narration already covered it.
_SPACE_MENTION_CUES: dict[str, tuple[str, ...]] = {
    "Bathroom": (
        "bathroom", "toilet", "shower", "vanity",
        "卫浴", "卫生间", "浴室", "淋浴", "马桶", "洗手台",
    ),
    "Kitchen": ("kitchen", "cooktop", "stove", "sink", "counter", "厨房", "灶", "水槽", "台面", "橱柜"),
    "Living Room": ("living", "sofa", "客厅", "沙发"),
    "Study Area": ("study", "desk", "书房", "书桌", "办公"),
    "Primary Bedroom": ("primary bedroom", "master", "主卧"),
    "Secondary Bedroom": ("bedroom", "卧室", "床"),
    "Bedroom Area": ("bedroom", "卧室", "床"),
    "Bedroom": ("bedroom", "卧室", "床"),
    "Hallway": ("hallway", "corridor", "走廊", "过道"),
    "Dining Room": ("dining", "餐厅"),
    "Balcony": ("balcony", "阳台"),
}

_INSTANCE_IN_TEXT = re.compile(
    r"\b((?:Bedroom|Kitchen|Bathroom|Study(?:\s+Room)?|Living\s+Room|Hallway|Guest\s+Bedroom)\s*\d+)\b"
    r"|((?:卧室|客卧|主卧|次卧|书房|厨房|客厅|卫生间|走廊)\s*\d+)",
    re.IGNORECASE,
)


def strip_instance_numbers(text: str) -> str:
    """Remove leaked room instance numbers from user-facing / feature text."""
    if not text:
        return text

    def _repl(m: re.Match) -> str:
        raw = (m.group(1) or m.group(2) or "").strip()
        return re.sub(r"\s*\d+$", "", raw).strip()

    return _INSTANCE_IN_TEXT.sub(_repl, text)


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / max(len(text), 1)


def _features_for_segment(seg: VKBSegment) -> list[str]:
    bits: list[str] = []
    for space in seg.knowledge.spaces or []:
        for feat in (space.features or [])[:2]:
            if feat:
                bits.append(strip_instance_numbers(str(feat)))
    for field in (
        seg.knowledge.selling_points or [],
        seg.knowledge.furniture or [],
        seg.knowledge.appliances or [],
    ):
        for item in field:
            if item:
                bits.append(strip_instance_numbers(str(item)))
    cjk = [b for b in bits if _cjk_ratio(b) >= 0.35]
    ordered = cjk if cjk else bits
    return list(dict.fromkeys(ordered))


def _needs_enrichment(text: str, language: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if language == "zh":
        if len(t) < 14:
            return True
        if any(t.endswith(end) for end in _INCOMPLETE_END_ZH):
            return True
        if _EMPTY_ZH.search(t) and len(t) < 28:
            return True
        if len(t) >= 28 and any(b in t for b in _BENEFIT_CUES_ZH):
            return False
        if len(t) >= 36:
            return False
        # Short complete sentence without benefit → enrich by appending
        if len(t) < 28 and not any(b in t for b in _BENEFIT_CUES_ZH):
            return True
        return False
    words = t.split()
    if len(words) < 8:
        return True
    low = t.lower()
    if any(p in low for p in ("serene sanctuary", "refined living", "timeless elegance")):
        return True
    return False


def _room_label_zh(room: str) -> str:
    mapping = {
        "Living Room": "客厅",
        "Kitchen": "厨房",
        "Bedroom": "卧室",
        "Primary Bedroom": "主卧",
        "Secondary Bedroom": "卧室",
        "Bedroom Area": "卧室",
        "Guest Bedroom": "卧室",
        "Bathroom": "卫生间",
        "Study Room": "书房",
        "Study Area": "书房",
        "Hallway": "走廊",
        "Dining Room": "餐厅",
        "Balcony": "阳台",
        "Mixed Private Area": "这一区域",
    }
    if room in mapping:
        return mapping[room]
    return room if _cjk_ratio(room) >= 0.35 else "这一区域"


# 「X旁的Y」 — only keep when the previous shot's primary room is X.
_ADJACENT_ROOM_ZH = re.compile(
    r"(?:书房|卧室|客卧|主卧|次卧|客厅|厨房|卫生间|餐厅|洗衣(?:房|区)?|阳台|走廊)旁的"
)
_ADJACENT_PLACEHOLDER = "\x00ADJ\x00"

_ROOM_WORD_ZH = r"(?:书房|卧室|客卧|主卧|次卧|客厅|厨房|卫生间|浴室|餐厅|洗衣(?:房|区|柜)?|洗烘(?:区|机)|阳台|走廊)"

# Room words → canonical space, for "is this clause about our room?" checks.
# Longest-first so 卫生间 wins over 生间 and 洗衣房 over 洗衣.
_ZH_ROOM_TOKENS: tuple[tuple[str, str], ...] = (
    ("卫生间", "Bathroom"),
    ("浴室", "Bathroom"),
    ("洗衣房", "Laundry Room"),
    ("洗烘区", "Laundry Room"),
    ("洗衣柜", "Laundry Room"),
    ("洗烘机", "Laundry Room"),
    ("洗衣区", "Laundry Room"),
    ("洗衣机", "Laundry Room"),
    ("衣帽间", "Closet"),
    ("客厅", "Living Room"),
    ("厨房", "Kitchen"),
    ("餐厅", "Dining Room"),
    ("卧室", "Bedroom"),
    ("书房", "Study Room"),
    ("阳台", "Balcony"),
    ("走廊", "Hallway"),
    ("过道", "Hallway"),
    ("玄关", "Entry"),
)

# "I am now standing in X" / "next door is X" — a foreign room in a clause that
# opens this way means the shot's subject drifted to another room.
_LOC_LEAD_ZH = re.compile(
    r"^(?:现在|我们|接着|然后|最后|首先)?[，、\s]*(?:先|再)?"
    r"(?:步入|走进|走入|来到|站在|位于|进入|转到|转过来是|这里是|这边是|这就是|这是"
    r"|前方是|前面是|回看|回望|望向|看向|转身|旁边(?:就)?是|旁侧|旁为"
    r"|一旁(?:便)?是|紧邻|隔壁(?:就)?是|旁边|一旁)"
)
# Access phrasing ("the bedroom opens onto the balcony") is a property of OUR
# room and stays, even though it names another space. Access that sells a
# furnished indoor room ("直通客厅") is the next shot's line.
_ACCESS_ZH = ("直通", "连通", "通向", "通往", "连接", "直达", "即达", "相连", "连着")
_ACCESS_KEEP_DEST = frozenset({"Balcony"})
_UNPLACED_ROOMS = frozenset({"", "Unknown", "Mixed Private Area", "Other", "N/A"})
# Spec-sheet leftovers the polish model still coins. Strip the phrase, not the
# room — "厨房是核心区域" must remain a kitchen line.
_BROCHURE_PHRASES_ZH = (
    "效率与隐私兼顾",
    "兼顾设计感与日常便利性",
    "采光与实用性兼备",
    "实用与格调兼备",
    "兼顾设计感",
    "效率与隐私",
    "核心生活区",
    "微开即见",
    "高效实用",
    "高效顺手",
    "核心区域",
)
_KITCHEN_PROP_ZH = ("嵌入式冰箱", "法式门冰箱", "洗碗机", "燃气灶", "冰箱", "烤箱", "微波炉", "灶台")
_NO_KITCHEN_PROP = frozenset({
    "Bedroom", "Bathroom", "Hallway", "Laundry Room", "Balcony",
    "Mixed Private Area", "Unknown",
})
# Invented room counting — Vision cannot reliably tell a second bathroom from
# the same one shot twice, so a spoken ordinal is a guess.
_ROOM_ORDINAL_ZH = re.compile(
    rf"(?:第[一二三四五六七八九十\d]+(?:间|个|处)|另(?:一)?(?:间|处|个)"
    rf"|其中(?:一)?(?:间|个)|又一(?:间|处))\s*(?={_ROOM_WORD_ZH})"
)


def _rooms_in_clause(clause: str) -> set[str]:
    """Canonical spaces named in this clause."""
    found: set[str] = set()
    residue = clause
    for token, canonical in _ZH_ROOM_TOKENS:
        if token in residue:
            found.add(canonical)
            residue = residue.replace(token, "\x00")
    return found


def _canonical_room(room: str) -> str:
    label = (room or "").strip()
    aliases = {
        "Primary Bedroom": "Bedroom",
        "Secondary Bedroom": "Bedroom",
        "Guest Bedroom": "Bedroom",
        "Bedroom Area": "Bedroom",
        "Study Area": "Study Room",
        "Laundry Area": "Laundry Room",
        "Corridor": "Hallway",
        "Mixed Private Area": "",
        "Unknown": "",
        "Other": "",
    }
    return aliases.get(label, label)


def _strip_adjacency_lead(clause: str) -> str:
    return re.sub(
        r"^(?:旁边(?:就)?是?|旁侧(?:是)?|旁为|一旁(?:便)?是?|紧邻(?:着)?|隔壁(?:就)?是?)",
        "",
        clause,
    ).lstrip("的，、 ")


def _split_clauses_zh(sentence: str) -> list[tuple[str, str]]:
    """Split into (body, trailing separator) pairs on ，、；."""
    out: list[tuple[str, str]] = []
    body = ""
    for ch in sentence:
        if ch in "，、；;" or ch in "—–―":
            out.append((body, ch))
            body = ""
        else:
            body += ch
    if body:
        out.append((body, ""))
    return out


def enforce_single_room_subject(
    text: str,
    *,
    room_type: str = "",
    allowed_rooms: tuple[str, ...] | list[str] = (),
    language: str = "zh",
) -> str:
    """Keep the shot's own room as the subject of every clause.

    A walkthrough line must describe the room the camera is standing in.
    Clauses that step into another room ("现在步入走廊…") or sell its contents
    ("旁边卧室可见大床…") are dropped; access phrasing ("直通阳台") stays.
    """
    if language != "zh" or not (text or "").strip():
        return text

    own = _canonical_room(room_type)
    known = {canonical for _, canonical in _ZH_ROOM_TOKENS}
    unplaced = own not in known or (room_type or "").strip() in _UNPLACED_ROOMS
    allowed = {own} if own in known else set()
    allowed.update(_canonical_room(r) for r in (allowed_rooms or ()))
    allowed.discard("")

    sentences = re.findall(r"[^。！？]+[。！？]?", text)
    rebuilt_sentences: list[str] = []
    dropped_any = False

    for sentence in sentences:
        match = re.search(r"[。！？]$", sentence)
        ender = match.group(0) if match else ""
        core = sentence[: -len(ender)] if ender else sentence
        clauses = _split_clauses_zh(core)
        kept: list[tuple[str, str]] = []
        for body, sep in clauses:
            stripped = body.strip()
            if not stripped:
                continue
            foreign = _rooms_in_clause(stripped) - allowed
            if own in _NO_KITCHEN_PROP and any(p in stripped for p in _KITCHEN_PROP_ZH):
                dropped_any = True
                continue
            if not foreign:
                kept.append((stripped, sep))
                continue
            if _LOC_LEAD_ZH.match(stripped):
                dropped_any = True
                continue
            if any(cue in stripped for cue in _ACCESS_ZH):
                dest = foreign
                if (
                    not unplaced
                    and dest <= _ACCESS_KEEP_DEST
                    and own in {"Bedroom", "Living Room", "Kitchen", "Dining Room"}
                ):
                    kept.append((stripped, sep))
                    continue
                dropped_any = True
                continue
            # Anything else that names another room is that room's line, not
            # ours — 「角落整合了洗衣区」 belongs to the laundry shot.
            dropped_any = True

        if not kept:
            # Mixed / Unknown must not restore a line that only sells a room
            # the camera is not in (hallway close reading the living room).
            if unplaced:
                dropped_any = True
                continue
            rebuilt_sentences.append(sentence)
            continue

        # 「旁边这间卧室…」 — our own room, introduced as if it were elsewhere.
        kept = [
            (_strip_adjacency_lead(body), sep) if _rooms_in_clause(body) & allowed
            else (body, sep)
            for body, sep in kept
        ]
        kept = [(body, sep) for body, sep in kept if body]
        if not kept:
            rebuilt_sentences.append(sentence)
            continue

        body = "".join(
            b + (s if i < len(kept) - 1 else "") for i, (b, s) in enumerate(kept)
        )
        body = body.rstrip("，、；; ")
        rebuilt_sentences.append(body + (ender or "。"))

    out = "".join(rebuilt_sentences).strip()
    if not out:
        return "" if unplaced else text
    if dropped_any:
        out = re.sub(r"[，、]{2,}", "，", out)
        out = re.sub(r"^(是|的|，|、|——|—)+", "", out).strip()
    return out or ("" if unplaced else text)
# 「；旁为卧室，床品整洁…」 — the shot is not that room; the whole trailing
# clause group belongs to a space the camera only passed. Drop it rather than
# cut inside it, so what is left is still a whole sentence.
_ADJACENT_TAIL_ZH = re.compile(
    r"[；;]\s*(?:旁为|旁侧|旁边(?:就)?是|一旁(?:便)?是|紧邻|隔壁(?:就)?是)"
    rf"{_ROOM_WORD_ZH}[^；;。！？]*"
)
# 主卫生间 / 次卫生间 must lose only the rank character. Replacing 「次卫」
# blindly leaves 「卫生间生间」.
_BATH_RANK_PREFIX_ZH = re.compile(r"[主次客](?=卫生间)")
_BATH_RANK_SHORT_ZH = re.compile(r"[主次客]卫(?![生浴])")


def sanitize_unverified_room_ranks(
    text: str,
    *,
    must_mention: list[str] | None = None,
    main_space: str = "",
    language: str = "zh",
    previous_primary: str = "",
    adjacent_ok: bool = False,
) -> str:
    """Strip guessed 主/次/客/书房 and invented adjacent-room phrases."""
    if language != "zh" or not (text or "").strip():
        return text
    allowed = set(must_mention or [])
    main = (main_space or "").strip()
    out = text
    prev_zh = _room_label_zh(previous_primary) if previous_primary else ""
    keep_adj = bool(adjacent_ok and prev_zh)
    if keep_adj:
        out = out.replace(f"{prev_zh}旁的", _ADJACENT_PLACEHOLDER)
        out = out.replace(f"{prev_zh}旁", _ADJACENT_PLACEHOLDER)
    out = _ADJACENT_ROOM_ZH.sub("", out)
    if not keep_adj:
        out = _ADJACENT_TAIL_ZH.sub("", out)
    if "Primary Bedroom" not in allowed:
        out = out.replace("主卧", "卧室")
    if "Secondary Bedroom" not in allowed:
        out = out.replace("次卧", "卧室")
    # Same rank-guess rule for bathrooms — 主卫/次卫 without evidence is just 卫生间.
    out = _BATH_RANK_PREFIX_ZH.sub("", out)
    out = _BATH_RANK_SHORT_ZH.sub("卫生间", out)
    if "Guest Bedroom" not in allowed:
        guest_to = "客厅" if main in ("Living Room", "客厅") or "沙发" in out else "卧室"
        out = out.replace("客卧", guest_to).replace("客房", guest_to)
    study_allowed = "Study Area" in allowed or "Study Room" in allowed
    if not study_allowed and not (keep_adj and prev_zh == "书房"):
        out = out.replace("书房旁的", "").replace("书房旁", "")
        out = out.replace("书房区", "").replace("独立书房", "")
        out = out.replace("书房", "")
    if keep_adj:
        out = out.replace(_ADJACENT_PLACEHOLDER, f"{prev_zh}旁的")
    # 「第二间卫生间」/「另一间卧室」 — spoken counting the tour cannot verify.
    # Two shots of one bathroom become "two bathrooms" and the buyer loses count.
    out = _ROOM_ORDINAL_ZH.sub("", out)
    out = re.sub(r"[，、]{2,}", "，", out)
    out = re.sub(r"^(是|的|，|、)+", "", out)
    # Dropping a clause can leave the separator that introduced it.
    out = re.sub(r"[，、；;]+(?=[。！？]|$)", "", out)
    return out.strip()


def sanitize_timeline_narration(
    text: str,
    *,
    room_type: str = "",
    language: str = "zh",
    allowed_rooms: tuple[str, ...] | list[str] = (),
) -> str:
    """Post-unify / post-polish gate: only keep rank words Vision committed."""
    rt = (room_type or "").strip()
    must: list[str] = []
    if rt == "Primary Bedroom":
        must.append("Primary Bedroom")
    if rt == "Guest Bedroom":
        must.append("Guest Bedroom")
    if rt in ("Study Area", "Study Room"):
        must.append(rt)
    out = sanitize_unverified_room_ranks(
        text, must_mention=must, main_space=rt, language=language,
    )
    out = _strip_brochure_zh(out, language=language)
    out = enforce_single_room_subject(
        out, room_type=rt, allowed_rooms=allowed_rooms, language=(language or "zh").lower(),
    )
    return strip_bathroom_house_style(out, room_type=rt, language=language)


def _strip_brochure_zh(text: str, *, language: str = "zh") -> str:
    """Drop spec-sheet filler without deleting the room being named."""
    if (language or "zh").lower() != "zh" or not (text or "").strip():
        return text
    out = text
    for phrase in _BROCHURE_PHRASES_ZH:
        out = out.replace(phrase, "")
    out = re.sub(r"[是的][：:]", "", out)
    out = re.sub(r"[A-Za-z]{3,}", "", out)
    out = re.sub(r"[，、]{2,}", "，", out)
    out = re.sub(r"^[，、；;：:\s]+", "", out)
    out = re.sub(r"[，、；;]+(?=[。！？]|$)", "", out)
    return out.strip() or text


def _space_mentioned(text: str, narration_name: str) -> bool:
    low = (text or "").lower()
    cues = _SPACE_MENTION_CUES.get(narration_name)
    if cues:
        return any(c.lower() in low for c in cues)
    return narration_name.lower() in low or _room_label_zh(narration_name) in (text or "")


def _bathroom_clause(seg: VKBSegment, language: str) -> str:
    bath = next(
        (s for s in (seg.knowledge.spaces or []) if (s.type or "") == "Bathroom"),
        None,
    )
    feats = [strip_instance_numbers(f) for f in ((bath.features if bath else []) or [])[:2] if f]
    if language == "zh":
        if feats:
            usable = [f for f in feats if _cjk_ratio(f) >= 0.35][:2]
            if usable:
                return f"卫生间配备{'、'.join(usable)}，日常起居更便利"
            blob = " ".join(feats).lower()
            parts = []
            if "shower" in blob:
                parts.append("淋浴间")
            if "toilet" in blob:
                parts.append("马桶")
            if "vanity" in blob:
                parts.append("洗手台")
            if parts:
                return f"卫生间配备{'、'.join(parts)}，日常起居更便利"
        return "卫生间设施齐全，日常起居更便利"
    feat_part = ", ".join(feats[:2]) if feats else "practical fixtures"
    return f"the bathroom adds {feat_part} for everyday convenience"


def ensure_required_space_coverage(
    texts: dict[str, str],
    vkb: VisionKnowledgeBase,
    language: str = "zh",
) -> dict[str, str]:
    """If VKB lists Bathroom in a segment, force it into narration when missing."""
    by_id = {seg.segment_id: seg for seg in vkb.segments}
    lang = (language or "en").lower()
    out: dict[str, str] = {}
    for seg_id, text in texts.items():
        seg = by_id.get(seg_id)
        cleaned = strip_instance_numbers(text or "")
        if seg is None:
            out[seg_id] = cleaned
            continue
        labels = [
            narration_label(s) for s in (seg.knowledge.spaces or []) if narration_label(s)
        ]
        if any(l == "Bathroom" for l in labels) and not _space_mentioned(cleaned, "Bathroom"):
            clause = _bathroom_clause(seg, lang)
            base = cleaned.strip().rstrip("。.!，, ")
            cleaned = f"{base}；{clause}。" if lang == "zh" else f"{base}; {clause}."
        out[seg_id] = strip_instance_numbers(cleaned)
    return out


def ensure_timeline_space_coverage(
    narration_segments: list[dict],
    vkb: VisionKnowledgeBase | dict | None,
    language: str = "zh",
) -> list[dict]:
    """Post-unify/polish guard: Bathroom in source VKB must appear in spoken text."""
    if not narration_segments:
        return narration_segments
    if isinstance(vkb, dict):
        vkb = VisionKnowledgeBase(**vkb)
    if vkb is None:
        return narration_segments

    by_id = {seg.segment_id: seg for seg in vkb.segments}
    lang = (language or "en").lower()
    out: list[dict] = []
    for entry in narration_segments:
        item = dict(entry)
        text = strip_instance_numbers(str(item.get("text") or ""))
        source_ids = item.get("source_ids") or []
        if not source_ids and item.get("segment_id"):
            # draft scripts use scene ids directly
            source_ids = [item["segment_id"]]
        # Only speak for a bathroom the camera is actually in. A bathroom
        # glimpsed through a doorway used to be forced into the living-room
        # line, which is the "naming rooms we are not in" problem again.
        own_room = str(item.get("room_type") or "")
        bath_seg = None
        for sid in source_ids:
            seg = by_id.get(sid)
            if seg is None:
                continue
            spaces = seg.knowledge.spaces or []
            in_bathroom = own_room == "Bathroom" or any(
                (s.type or "") == "Bathroom" and (s.room_role or "") == "primary"
                for s in spaces
            )
            if in_bathroom:
                bath_seg = seg
                break
        if bath_seg is not None and not _space_mentioned(text, "Bathroom"):
            clause = _bathroom_clause(bath_seg, lang)
            base = text.strip().rstrip("。.!，, ")
            text = f"{base}；{clause}。" if lang == "zh" else f"{base}; {clause}."
        item["text"] = strip_instance_numbers(text)
        out.append(item)
    return out


# Phrases every room in a listing shares. Said once they set the style; said
# again they replace the reason a buyer would remember that room.
_GENERIC_GROUPS_ZH: dict[str, tuple[str, ...]] = {
    "floor": (
        "深色实木地板", "深色木纹地板", "深色木地板", "深色地板", "深色地砖",
        "木纹地板", "实木地板", "木地板",
    ),
    "wall": ("白色墙面", "白色墙壁", "白墙"),
    "window": ("大面积落地窗", "整面落地窗", "落地玻璃窗", "落地窗", "大窗", "大面窗"),
    "view": ("城市天际线", "城市景观", "城市风景", "城市视野"),
    "light": (
        "采光充足", "自然光充足", "光线充足", "通透明亮", "通透敞亮", "明亮通透",
        "引入自然光", "充足自然光", "自然光", "日间光线", "日光", "采光", "通透",
    ),
}
# Connective / mood filler. What is left after removing these and the generic
# phrases is the clause's actual evidence.
_GENERIC_FILLER_ZH = (
    "搭配", "配以", "配上", "延续", "延伸", "通铺", "铺设", "铺贴", "整体", "全屋",
    "空间", "视野", "开阔", "宽敞", "舒适", "安静", "宁静", "沉稳", "大气", "统一",
    "连贯", "干净", "简洁", "清爽", "利落", "从容", "使用体验", "体验", "格调",
    "勾勒", "沉静",
    "一览无余", "尽收眼底", "映入眼帘", "格外", "显得",
    "更加", "非常", "同样", "也是", "还有", "以及", "并且", "引入", "室内", "而",
)
# A bathroom is sold on fixtures. House-style floors / walls / windows belong
# to the living room or bedroom and read as filler (or a lie) in a bath.
_BATHROOM_FIXTURE_ZH = (
    "马桶", "坐便", "水箱", "台盆", "洗手台", "洗手", "淋浴", "浴缸", "浴盆",
    "花洒", "镜", "水槽", "干湿分离", "卫浴",
)


def _generic_groups_in(clause: str) -> set[str]:
    return {
        group
        for group, phrases in _GENERIC_GROUPS_ZH.items()
        if any(p in clause for p in phrases)
    }


def _is_purely_generic_zh(clause: str) -> bool:
    """True when the clause carries no evidence beyond shared house style.

    The room's own name does not count as evidence — "这间卧室同样铺深色木地板"
    tells the buyer nothing they have not already heard about two other rooms.
    """
    residue = clause
    for phrases in _GENERIC_GROUPS_ZH.values():
        for phrase in phrases:
            residue = residue.replace(phrase, "")
    for token, _ in _ZH_ROOM_TOKENS:
        residue = residue.replace(token, "")
    for filler in _GENERIC_FILLER_ZH:
        residue = residue.replace(filler, "")
    residue = re.sub(r"[^\u4e00-\u9fff]", "", residue)
    residue = re.sub(r"[这那是的了也又与和在向到就都很间处个铺设有着看]", "", residue)
    return len(residue) <= 2


def _bathroom_keep_clause(clause: str) -> bool:
    """Keep fixture evidence, or a room name that is not just house style."""
    if any(token in clause for token in _BATHROOM_FIXTURE_ZH):
        return True
    return bool(_rooms_in_clause(clause)) and not _generic_groups_in(clause)


def _rebuild_zh_kept(clauses: list[tuple[str, str]], ender: str) -> str:
    kept: list[tuple[str, str]] = [(body.strip(), sep) for body, sep in clauses if body.strip()]
    if not kept:
        return ""
    body = "".join(
        b + (s if i < len(kept) - 1 else "") for i, (b, s) in enumerate(kept)
    ).rstrip("，、；; ")
    return body + (ender or "。")


def strip_bathroom_house_style(
    text: str,
    *,
    room_type: str = "",
    language: str = "zh",
) -> str:
    """A bathroom line may name fixtures. It may not resell the house style."""
    if (language or "zh").lower() != "zh" or not (text or "").strip():
        return text
    if _canonical_room(room_type) != "Bathroom":
        return text

    rebuilt: list[str] = []
    for sentence in re.findall(r"[^。！？]+[。！？]?", text):
        match = re.search(r"[。！？]$", sentence)
        ender = match.group(0) if match else ""
        core = sentence[: -len(ender)] if ender else sentence
        clauses = _split_clauses_zh(core)
        kept = [(body, sep) for body, sep in clauses if _bathroom_keep_clause(body)]
        if not kept:
            first = next((c for c in clauses if c[0].strip()), None)
            if first is None:
                continue
            kept = [first]
        rebuilt.append(_rebuild_zh_kept(kept, ender))
    cleaned = "".join(rebuilt).strip()
    return cleaned or text


def dedupe_generic_atmosphere(
    narration_segments: list[dict],
    language: str = "zh",
    max_uses: int = 1,
) -> list[dict]:
    """Stop the tour from describing every room with the same three phrases.

    Dark floors / white walls / city view may set the tone once. Past that, a
    clause built only from them is dropped. Bathrooms never get the house
    style — they keep toilets, vanities, showers.
    """
    if (language or "en").lower() != "zh" or not narration_segments:
        return narration_segments

    used: dict[str, int] = {}
    out: list[dict] = []
    for index, entry in enumerate(narration_segments):
        item = dict(entry)
        text = strip_bathroom_house_style(
            str(item.get("text") or ""),
            room_type=str(item.get("room_type") or ""),
            language=language,
        )
        item["text"] = text
        # The opening names where the tour starts; thinning it leaves a mute
        # hallway. The close used to be exempt and then recycled the same
        # floors / white walls / city view over a hallway shot.
        if not text.strip() or index == 0:
            for sentence in re.findall(r"[^。！？]+[。！？]?", text):
                for body, _ in _split_clauses_zh(sentence):
                    for group in _generic_groups_in(body):
                        used[group] = used.get(group, 0) + 1
            out.append(item)
            continue

        rebuilt: list[str] = []
        for sentence in re.findall(r"[^。！？]+[。！？]?", text):
            match = re.search(r"[。！？]$", sentence)
            ender = match.group(0) if match else ""
            core = sentence[: -len(ender)] if ender else sentence
            clauses = _split_clauses_zh(core)
            kept: list[tuple[str, str]] = []
            for body, sep in clauses:
                stripped = body.strip()
                if not stripped:
                    continue
                groups = _generic_groups_in(stripped)
                # A clause naming the room is the line's anchor — dropping it
                # would leave the shot describing scenery with no room attached.
                anchored = bool(_rooms_in_clause(stripped))
                if (
                    groups
                    and not anchored
                    and _is_purely_generic_zh(stripped)
                    and all(used.get(g, 0) >= max_uses for g in groups)
                ):
                    continue
                for group in groups:
                    used[group] = used.get(group, 0) + 1
                kept.append((stripped, sep))
            if not kept:
                # Never leave a segment mute. Keep the opening clause only — it
                # carries the room we are standing in — and drop the rest of the
                # repeated style words.
                first = next((c for c in clauses if c[0].strip()), None)
                if first is None:
                    continue
                for group in _generic_groups_in(first[0]):
                    used[group] = used.get(group, 0) + 1
                rebuilt.append(first[0].strip() + (ender or "。"))
                continue
            body = "".join(
                b + (s if i < len(kept) - 1 else "") for i, (b, s) in enumerate(kept)
            ).rstrip("，、；; ")
            rebuilt.append(body + (ender or "。"))

        cleaned = "".join(rebuilt).strip()
        item["text"] = cleaned or text
        out.append(item)
    return out


def enrich_marketing_texts(
    texts: dict[str, str],
    vkb: VisionKnowledgeBase,
    language: str = "zh",
) -> dict[str, str]:
    """Fill missing evidence/benefit layers using VKB facts only."""
    by_id = {seg.segment_id: seg for seg in vkb.segments}
    out: dict[str, str] = {}
    lang = (language or "en").lower()

    for seg_id, text in texts.items():
        seg = by_id.get(seg_id)
        text = strip_instance_numbers(text or "")
        if seg is None or not _needs_enrichment(text, lang):
            out[seg_id] = text
            continue

        feats = _features_for_segment(seg)[:2]
        base = (text or "").strip().rstrip("。.!，, ")

        if lang == "zh":
            if feats:
                usable = [f for f in feats if _cjk_ratio(f) >= 0.35][:2]
                if usable:
                    feat_part = "、".join(usable)
                    out[seg_id] = f"{base}，可见{feat_part}，提升日常居住便利。"
                else:
                    out[seg_id] = (
                        f"{base}，{_room_label_zh(seg.knowledge.room_type or '')}"
                        f"功能配置清晰，兼顾设计感与日常实用性。"
                    )
            else:
                out[seg_id] = (
                    f"{base}，{_room_label_zh(seg.knowledge.room_type or '')}"
                    f"布局实用，提升日常居住便利。"
                )
        else:
            feat_part = ", ".join(feats[:2]) if feats else "practical fixtures"
            out[seg_id] = (
                f"{base}, with {feat_part} that support comfortable daily living."
            )
    return ensure_required_space_coverage(out, vkb, language=lang)
