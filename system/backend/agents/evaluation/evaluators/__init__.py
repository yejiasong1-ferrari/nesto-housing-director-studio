"""Shared helpers for evaluation modules."""

from __future__ import annotations

import re
from typing import Any


ROOM_KEYWORDS: dict[str, set[str]] = {
    "kitchen": {
        "kitchen", "cabinet", "counter", "stove", "range", "refrigerator",
        "sink", "island", "oven", "dishwasher",
    },
    "bedroom": {
        "bedroom", "bed", "mattress", "nightstand", "closet", "studio",
    },
    "bathroom": {
        "bathroom", "bath", "vanity", "shower", "tub", "toilet", "tile",
    },
    "hallway": {
        "hallway", "stair", "landing", "skylight", "railing", "foyer",
    },
    "closet": {
        "closet", "hanging", "wardrobe", "shoe",
    },
    "exterior": {
        "facade", "brick", "entrance", "exterior", "front door", "porch",
    },
    "living": {
        "living", "sofa", "couch", "lounge",
    },
}


def safe_id(segment_id: str) -> str:
    return str(segment_id or "").split("[", 1)[0]


def normalize_room(room: str) -> str:
    r = (room or "").lower()
    for key in ROOM_KEYWORDS:
        if key in r:
            return key
    return r.split("(")[0].strip() or "unknown"


def room_keywords_in_text(text: str) -> set[str]:
    t = (text or "").lower()
    found: set[str] = set()
    for room, kws in ROOM_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(k)}\b", t) for k in kws):
            found.add(room)
    return found


def index_by_safe_id(items: list[dict], id_key: str = "id") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in items:
        sid = safe_id(str(item.get(id_key) or item.get("segment_id") or ""))
        if sid:
            out[sid] = item
    return out


def vision_room_at_time(vision: dict[str, Any], t: float) -> str:
    """Return vision room_type covering timestamp t (source video time)."""
    best = ""
    for seg in vision.get("segments", []) or []:
        raw = seg.get("raw", {})
        start = float(raw.get("start_time", 0) or 0)
        end = float(raw.get("end_time", 0) or 0)
        if start <= t < end or (abs(end - start) < 1e-6 and abs(t - start) < 0.05):
            kn = seg.get("knowledge", {})
            best = raw.get("room_type") or kn.get("room_type") or best
    return best


def clamp_score(x: float) -> float:
    return round(max(0.0, min(100.0, x)), 1)
