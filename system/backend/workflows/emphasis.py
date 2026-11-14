"""Director emphasis intake + presence gating (workflow layer — not an Agent).

The user brief may ask to emphasize a specific object (e.g. "多介绍床" /
"highlight the bed"). We honor that request in narration and visual focus —
but ONLY when the object actually appears in a segment's Vision facts. If the
object is not present in the footage, we never fabricate it.

This module defines the single "presence standard" reused by:
  - Planner attention scoring (which segment matters)
  - Script Scene Narrator (what to say more about)
  - Timeline analyzer (what to visually focus on)

Cognition (deciding WHAT the user wants) stays in the Planner; this helper only
provides deterministic string matching against VKB facts.
"""

from __future__ import annotations

import re

# Canonical object → bilingual synonyms (substring match, lowercased).
# Keep entries concrete and visually verifiable; avoid abstract mood words.
OBJECT_SYNONYMS: dict[str, list[str]] = {
    "bed": ["bed", "床", "床铺", "卧床"],
    "sofa": ["sofa", "couch", "沙发"],
    "wardrobe": ["wardrobe", "closet", "衣柜", "衣橱"],
    "desk": ["desk", "书桌", "办公桌", "写字台"],
    "dining table": ["dining table", "dining", "餐桌", "饭桌"],
    "table": ["table", "桌", "茶几"],
    "chair": ["chair", "椅", "座椅"],
    "tv": ["tv", "television", "电视"],
    "fridge": ["fridge", "refrigerator", "冰箱"],
    "stove": ["stove", "range", "cooktop", "oven", "灶", "炉", "烤箱"],
    "microwave": ["microwave", "微波炉"],
    "washer": ["washer", "washing machine", "dryer", "洗衣机", "烘干机"],
    "sink": ["sink", "水槽", "洗手台", "台盆"],
    "island": ["island", "中岛", "岛台", "中央岛"],
    "cabinet": ["cabinet", "cupboard", "橱柜", "柜子", "储物柜"],
    "countertop": ["countertop", "counter", "台面", "灶台"],
    "window": ["window", "窗", "窗户", "落地窗"],
    "balcony": ["balcony", "terrace", "阳台", "露台"],
    "bathtub": ["bathtub", "tub", "浴缸"],
    "shower": ["shower", "淋浴", "花洒"],
    "vanity": ["vanity", "梳妆", "洗漱台"],
    "fireplace": ["fireplace", "壁炉"],
    "shelf": ["shelf", "shelving", "bookshelf", "架", "书架", "置物架"],
    "rug": ["rug", "carpet", "地毯"],
    "lighting": ["lamp", "light", "chandelier", "灯", "吊灯", "采光", "光线"],
    "flooring": ["hardwood", "floor", "地板", "木地板", "瓷砖"],
    "kitchen": ["kitchen", "厨房", "kitchenette"],
    "bedroom": ["bedroom", "卧室", "主卧", "次卧"],
    "living room": ["living", "客厅", "起居"],
    "bathroom": ["bathroom", "浴室", "卫生间", "洗手间", "厕所", "toilet"],
    "closet space": ["walk-in", "walk in", "储藏", "步入式"],
}

# Verbs signalling the user is asking to emphasize something.
_EMPHASIS_MARKERS = (
    "highlight", "focus", "emphasize", "emphasise", "showcase", "feature",
    "more about", "more on", "show more",
    "突出", "重点", "多介绍", "多讲", "强调", "着重", "多说", "主打",
)

_EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "please", "want", "would", "like", "make", "video", "this", "that",
    "more", "about", "some", "show", "showcase", "highlight", "focus",
    "emphasize", "emphasise", "feature", "featuring", "room", "space",
    "property", "house", "home", "apartment", "tour", "walkthrough",
}


def has_emphasis_request(text: str) -> bool:
    """True if the brief explicitly asks to emphasize/highlight something."""
    if not text:
        return False
    low = text.lower()
    return any(m in low or m in text for m in _EMPHASIS_MARKERS)


def parse_emphasis_targets(text: str) -> list[str]:
    """Extract canonical emphasis targets from the ORIGINAL user brief.

    Returns canonical keys (e.g. ["bed", "window"]). Empty when the brief is
    generic. Only the user's real words are used — never the expanded default.
    """
    if not text:
        return []
    low = text.lower()

    targets: list[str] = []
    for canonical, syns in OBJECT_SYNONYMS.items():
        if any(s in low or s in text for s in syns):
            targets.append(canonical)

    # Also keep concrete English nouns the user typed that we don't model yet,
    # so arbitrary requested items still get presence-gated downstream.
    for word in re.findall(r"[a-zA-Z]{3,}", low):
        if word in _EN_STOPWORDS:
            continue
        if word in targets:
            continue
        # skip if already covered by an existing canonical synonym
        if any(word in syns for syns in OBJECT_SYNONYMS.values()):
            continue
        targets.append(word)

    # de-dup preserving order
    return list(dict.fromkeys(targets))


def _synonyms(target: str) -> list[str]:
    return OBJECT_SYNONYMS.get(target, [target])


def _knowledge_facts(knowledge: dict) -> list[str]:
    """Concrete VKB fact strings usable for presence checks (original case)."""
    facts: list[str] = []
    for key in ("selling_points", "furniture", "appliances"):
        vals = knowledge.get(key) or []
        facts.extend(str(v) for v in vals if str(v).strip())
    return facts


def target_present(target: str, knowledge: dict) -> bool:
    """True if the requested target appears in this segment's VKB facts/room."""
    syns = _synonyms(target)
    haystack = " ".join(
        [str(knowledge.get("room_type", ""))]
        + _knowledge_facts(knowledge)
        + [str(knowledge.get("notes", "")), str(knowledge.get("style", ""))]
    ).lower()
    return any(s.lower() in haystack for s in syns)


def matched_facts(targets: list[str], knowledge: dict) -> list[str]:
    """Return the VKB fact strings that satisfy any requested target.

    These are real on-screen items — safe to promote in narration / focus
    without fabrication. Room-only matches (no concrete fact) yield [].
    """
    if not targets:
        return []
    facts = _knowledge_facts(knowledge)
    out: list[str] = []
    for fact in facts:
        fl = fact.lower()
        for t in targets:
            if any(s.lower() in fl for s in _synonyms(t)):
                out.append(fact)
                break
    return list(dict.fromkeys(out))


def present_targets(targets: list[str], knowledge: dict) -> list[str]:
    """Subset of requested targets that are actually present in this segment."""
    return [t for t in targets if target_present(t, knowledge)]
