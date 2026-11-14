"""Long Segment Re-analysis — Property Space Understanding Layer.

CLIP segmentation produces coarse temporal segments. A long segment
(e.g. 9–20s) often contains multiple rooms that a single room_type
cannot represent. This module re-samples keyframes across the segment
and asks the Vision LLM to inventory all unique spaces.

Does NOT re-segment the video. Keeps existing segment boundaries.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.schemas.vision_schema import RoomKnowledge, SpaceEvidence, SpaceInventoryItem, VKBSegment

logger = logging.getLogger(__name__)

DEFAULT_DURATION_THRESHOLD = 8.0
DEFAULT_SAMPLE_COUNT = 4
DEFAULT_CONFIDENCE_TRIGGER = 0.7

# Mean luminance / file-size heuristics for junk frames
BLACK_MEAN_MAX = 18.0
BLACK_STD_MAX = 12.0
LOW_INFO_STD_MAX = 14.0
MIN_FILE_BYTES = 2500

INVENTORY_SYSTEM_PROMPT = """You are a professional real estate spatial analyst.
You identify DISTINCT rooms/spaces shown across a sequence of walkthrough frames.

Your job is Property Space Understanding — NOT marketing copy.

Rules:
- List every UNIQUE room/space the camera clearly ENTERS or dwells in.
- A space should be included if it is clearly visible, even if briefly appears.
- Two bedrooms that look different (different beds, layouts, or wall colors) are SEPARATE spaces.
- A study / home office with a desk is distinct from a bedroom.
- Kitchen and Bathroom are distinct — if both appear, list BOTH with evidence features.
- ONLY list Bathroom when a toilet, shower, bathtub, or washroom fixtures are VISIBLE in the frames.
- Do NOT invent Bathroom / Bedroom from closed doors, hallway glimpses, or phrases like "likely bathroom".
- Kitchen with wall tiles is still a Kitchen — tiling alone is not a Bathroom.
- If frames show the SAME continuous room from different angles, list it ONCE.
- IGNORE brief doorway / hallway glimpses of rooms that are only partially visible in the background.
- IGNORE black frames, logo screens, end-title cards, and watermark-only frames — they are not rooms.
- Prefer specific labels: Bedroom, Study Room, Living Room, Kitchen, Bathroom, Hallway, Dining Room, Closet, Balcony.
- Do NOT return "Mixed Private Area" as a space type — expand it into concrete rooms.
- Do NOT force a single room_type when multiple spaces appear.
- For each space, keep evidence features that justify the label (toilet, shower, cooktop, bed, desk, …).
- Return ONLY valid JSON. No markdown. No explanation.

JSON schema:
{
  "spaces": [
    {
      "type": "Bathroom",
      "confidence": 0.9,
      "features": ["toilet", "glass shower", "vanity"]
    }
  ]
}
"""

# Keywords in Module-4 facts that imply a secondary room type.
# Bathroom requires fixture-level evidence — bare "bathroom" / "vanity" alone
# is too weak (closed-door speculation, bedroom vanity, tiled kitchens).
ROOM_EVIDENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Bathroom": (
        "toilet", "shower", "bathtub", "bath tub", "bidet", "wc", "lavatory",
        "showerhead", "shower enclosure", "shower stall", "washroom",
    ),
    "Kitchen": (
        "kitchen", "cooktop", "stove", "oven", "range hood", "refrigerator",
        "fridge", "dishwasher", "countertop",
    ),
    "Bedroom": ("bedroom", "headboard", "mattress"),
    "Study Room": ("study", "desk", "bookshelf", "home office"),
    "Living Room": ("living room", "sofa", "sectional", "coffee table"),
    "Dining Room": ("dining room", "dining table"),
    "Hallway": ("hallway", "corridor"),
    "Balcony": ("balcony", "terrace"),
    "Laundry Room": ("laundry", "washer", "dryer"),
}

# Speculative / off-camera phrasing — never mint a room from these alone.
_SPECULATIVE_EVIDENCE = re.compile(
    r"\b(likely|possibly|perhaps|appears to|seem(?:s)? to|may be|might be|"
    r"probably|potential(?:ly)?|behind (?:the )?door|leading to|"
    r"interior doors?|closed doors?)\b",
    re.IGNORECASE,
)

# Fixture proof required before Bathroom may enter inventory / coverage.
_BATHROOM_FIXTURE_RE = re.compile(
    r"\b(toilet|shower(?:head| enclosure| stall)?|bathtub|bath\s*tub|bidet|"
    r"wc|lavatory|washroom)\b",
    re.IGNORECASE,
)


def _normalize_type(label: str) -> str:
    text = (label or "").strip()
    if not text:
        return "Unknown"
    text = re.sub(r"\s+\d+$", "", text).strip()
    aliases = {
        "study": "Study Room",
        "study room": "Study Room",
        "home office": "Study Room",
        "office": "Study Room",
        "bed room": "Bedroom",
        "master bedroom": "Bedroom",
        "guest bedroom": "Bedroom",
        "living": "Living Room",
        "lounge": "Living Room",
        "kitchenette": "Kitchen",
        "bath": "Bathroom",
        "bathroom": "Bathroom",
        "washroom": "Bathroom",
        "restroom": "Bathroom",
        "wc": "Bathroom",
        "toilet": "Bathroom",
        "mixed": "Mixed Private Area",
        "mixed private area": "Mixed Private Area",
        "private quarters": "Mixed Private Area",
        "unknown": "Unknown",
    }
    key = text.lower()
    if key in aliases:
        return aliases[key]
    return " ".join(w.capitalize() if w.islower() else w for w in text.split())


def _display_name(space_type: str, instance: int, type_counts: dict[str, int]) -> str:
    """Interim technical label; Room Naming Normalization rewrites before Planner."""
    if type_counts.get(space_type, 0) > 1:
        return f"{space_type} {instance}"
    return space_type


def _instance_id(space_type: str, instance: int) -> str:
    from backend.workflows.room_naming import make_instance_id

    return make_instance_id(space_type, instance)


def assign_instances(items: list[SpaceInventoryItem]) -> list[SpaceInventoryItem]:
    """Assign instance ids for duplicate room types (internal tracking)."""
    type_counts: dict[str, int] = {}
    for item in items:
        item.type = _normalize_type(item.type)
        type_counts[item.type] = type_counts.get(item.type, 0) + 1

    counters: dict[str, int] = {}
    result: list[SpaceInventoryItem] = []
    for item in items:
        counters[item.type] = counters.get(item.type, 0) + 1
        instance = counters[item.type]
        result.append(
            SpaceInventoryItem(
                type=item.type,
                instance=instance,
                instance_id=_instance_id(item.type, instance),
                confidence=item.confidence,
                features=list(dict.fromkeys(item.features or [])),
                display_name=_display_name(item.type, instance, type_counts),
                narration_name=getattr(item, "narration_name", "") or "",
                room_role=getattr(item, "room_role", "") or "",
                evidence=getattr(item, "evidence", None) or SpaceEvidence(),
            )
        )
    return result


def spaces_from_primary(knowledge: RoomKnowledge) -> list[SpaceInventoryItem]:
    """Fallback inventory from a single fused room_type."""
    room = _normalize_type(knowledge.room_type or "Unknown")
    features = list(
        dict.fromkeys(
            list(knowledge.selling_points or [])[:4]
            + list(knowledge.furniture or [])[:3]
        )
    )
    return assign_instances(
        [
            SpaceInventoryItem(
                type=room,
                instance=1,
                confidence=knowledge.confidence or 0.0,
                features=features,
            )
        ]
    )


def primary_room_type(spaces: list[SpaceInventoryItem], fallback: str = "Unknown") -> str:
    """Choose segment-level room_type from inventory."""
    if not spaces:
        return fallback or "Unknown"
    types = [s.type for s in spaces if s.type and s.type != "Unknown"]
    if not types:
        return fallback or "Unknown"
    unique = list(dict.fromkeys(types))
    if len(unique) == 1:
        return unique[0]
    return "Mixed Private Area"


def _knowledge_text(knowledge: RoomKnowledge) -> str:
    parts = [
        knowledge.room_type or "",
        knowledge.notes or "",
        " ".join(knowledge.selling_points or []),
        " ".join(knowledge.furniture or []),
        " ".join(knowledge.appliances or []),
    ]
    return " ".join(parts).lower()


def _is_speculative_phrase(text: str) -> bool:
    """True when the phrase is guessing off-camera rooms (closed doors, 'likely')."""
    return bool(_SPECULATIVE_EVIDENCE.search(text or ""))


def _has_bathroom_fixture_evidence(texts: list[str]) -> bool:
    """Bathroom may only be asserted when a real fixture is named."""
    blob = " ".join(str(t) for t in texts if t)
    if not blob.strip():
        return False
    if _is_speculative_phrase(blob) and not _BATHROOM_FIXTURE_RE.search(blob):
        return False
    # Reject "likely bedrooms/bathroom" style — bathroom token only inside speculation.
    if re.search(r"\bbathroom\b", blob, re.IGNORECASE) and _is_speculative_phrase(blob):
        if not _BATHROOM_FIXTURE_RE.search(
            re.sub(r"\bbathroom\b", " ", blob, flags=re.IGNORECASE)
        ):
            return False
    return bool(_BATHROOM_FIXTURE_RE.search(blob))


def bathroom_space_is_grounded(space: SpaceInventoryItem) -> bool:
    """Drop hallucinated Bathroom inventory that lacks fixture features."""
    if _normalize_type(space.type) != "Bathroom":
        return True
    return _has_bathroom_fixture_evidence(list(space.features or []))


def extract_evidence_rooms(knowledge: RoomKnowledge) -> dict[str, list[str]]:
    """Map implied room types → matching evidence phrases from Module-4 facts."""
    text = _knowledge_text(knowledge)
    found: dict[str, list[str]] = {}
    for room_type, keywords in ROOM_EVIDENCE_KEYWORDS.items():
        hits = [kw for kw in keywords if kw in text]
        if not hits:
            continue
        evidence: list[str] = []
        for field in (
            knowledge.selling_points or [],
            knowledge.furniture or [],
            knowledge.appliances or [],
            [knowledge.notes] if knowledge.notes else [],
        ):
            for item in field:
                raw = str(item)
                low = raw.lower()
                if not any(kw in low for kw in hits):
                    continue
                # Skip closed-door / "likely bathroom" speculation.
                if _is_speculative_phrase(raw):
                    continue
                evidence.append(raw)
        if room_type == "Bathroom":
            # Fixture gate — never mint Bathroom from bare "bathroom" / vanity.
            if not _has_bathroom_fixture_evidence(evidence or hits):
                continue
            # Prefer concrete fixture phrases over generic tokens
            evidence = [
                e for e in evidence
                if _BATHROOM_FIXTURE_RE.search(e) and not _is_speculative_phrase(e)
            ] or evidence
            if not evidence:
                continue
        if not evidence and room_type != "Bathroom":
            # Non-bathroom: keep keyword hits only when they came from real fields
            continue
        if evidence:
            found[room_type] = list(dict.fromkeys(evidence))
    return found


def has_room_evidence_conflict(knowledge: RoomKnowledge) -> bool:
    """True when Module-4 facts imply rooms other than the primary room_type."""
    primary = _normalize_type(knowledge.room_type or "")
    evidence = extract_evidence_rooms(knowledge)
    secondary = {
        room for room in evidence
        if room not in (primary, "Unknown", "Mixed Private Area")
    }
    if primary in ("Mixed Private Area", "Unknown") and len(evidence) >= 2:
        return True
    return len(secondary) >= 1


def merge_evidence_into_spaces(
    spaces: list[SpaceInventoryItem],
    knowledge: RoomKnowledge,
) -> list[SpaceInventoryItem]:
    """Ensure secondary rooms implied by Module-4 evidence appear in inventory."""
    evidence = extract_evidence_rooms(knowledge)
    by_type = {_normalize_type(s.type): s for s in spaces}
    for room_type, feats in evidence.items():
        if room_type in ("Unknown", "Mixed Private Area"):
            continue
        if room_type == "Bathroom" and not _has_bathroom_fixture_evidence(feats):
            continue
        if room_type in by_type:
            existing = by_type[room_type]
            existing.features = list(dict.fromkeys(list(existing.features or []) + feats))
        else:
            spaces.append(
                SpaceInventoryItem(
                    type=room_type,
                    confidence=max(0.55, min(0.85, (knowledge.confidence or 0.7) * 0.9)),
                    features=feats,
                )
            )
    # Prune hallucinated bathrooms already present (e.g. inventory LLM copy)
    spaces = [s for s in spaces if bathroom_space_is_grounded(s)]
    return assign_instances(spaces)


# ── Frame quality filtering ──────────────────────────────────


def score_frame_quality(image_path: str | Path) -> dict[str, float | bool | str]:
    """Score a frame for inventory usefulness (black / logo / low-info)."""
    import cv2
    import numpy as np

    path = Path(image_path)
    if not path.exists():
        return {"ok": False, "reason": "missing", "mean": 0.0, "std": 0.0, "file_bytes": 0}

    file_bytes = path.stat().st_size
    if file_bytes < MIN_FILE_BYTES:
        return {
            "ok": False,
            "reason": "tiny_file",
            "mean": 0.0,
            "std": 0.0,
            "file_bytes": float(file_bytes),
        }

    img = cv2.imread(str(path))
    if img is None:
        return {
            "ok": False,
            "reason": "unreadable",
            "mean": 0.0,
            "std": 0.0,
            "file_bytes": float(file_bytes),
        }

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean = float(np.mean(gray))
    std = float(np.std(gray))
    h, w = gray.shape[:2]

    if mean < BLACK_MEAN_MAX and std < BLACK_STD_MAX:
        return {"ok": False, "reason": "black", "mean": mean, "std": std, "file_bytes": float(file_bytes)}

    if std < LOW_INFO_STD_MAX and mean < 40:
        return {"ok": False, "reason": "low_info", "mean": mean, "std": std, "file_bytes": float(file_bytes)}

    # Logo / outro: mostly dark with a small bright text cluster in the center
    dark_ratio = float(np.mean(gray < 40))
    bright_ratio = float(np.mean(gray > 180))
    if dark_ratio > 0.82 and 0.002 < bright_ratio < 0.12 and mean < 55:
        cy0, cy1 = int(h * 0.25), int(h * 0.75)
        cx0, cx1 = int(w * 0.15), int(w * 0.85)
        center = gray[cy0:cy1, cx0:cx1]
        center_bright = float(np.mean(center > 180)) if center.size else 0.0
        edge = np.concatenate([
            gray[: max(1, h // 10), :].ravel(),
            gray[-max(1, h // 10) :, :].ravel(),
        ])
        edge_bright = float(np.mean(edge > 180)) if edge.size else 0.0
        if center_bright > edge_bright * 2 and center_bright > 0.01:
            return {
                "ok": False,
                "reason": "logo_outro",
                "mean": mean,
                "std": std,
                "file_bytes": float(file_bytes),
            }

    return {"ok": True, "reason": "ok", "mean": mean, "std": std, "file_bytes": float(file_bytes)}


def filter_quality_frames(paths: list[str]) -> list[str]:
    """Drop black / logo / low-information frames before Vision inventory."""
    kept: list[str] = []
    for path in paths:
        score = score_frame_quality(path)
        if score.get("ok"):
            kept.append(path)
        else:
            logger.info(
                "Frame quality filter drop %s (%s mean=%.1f std=%.1f)",
                Path(path).name,
                score.get("reason"),
                float(score.get("mean") or 0),
                float(score.get("std") or 0),
            )
    return kept


def select_sample_frames(
    frames: list[dict[str, Any]],
    start_time: float,
    end_time: float,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    fallback_keyframes: list[str] | None = None,
) -> list[str]:
    """Pick evenly spaced quality frames inside [start, end]."""
    in_range = [
        f
        for f in frames
        if start_time - 0.05 <= float(f.get("timestamp", 0)) <= end_time + 0.05
        and Path(str(f.get("frame_path", ""))).exists()
    ]

    candidates = [str(f["frame_path"]) for f in in_range]
    if not candidates and fallback_keyframes:
        candidates = [p for p in fallback_keyframes if Path(p).exists()]

    quality = filter_quality_frames(candidates)
    if not quality and fallback_keyframes:
        quality = filter_quality_frames([p for p in fallback_keyframes if Path(p).exists()])
    if not quality:
        quality = [p for p in (fallback_keyframes or candidates) if Path(p).exists()]

    if len(quality) <= sample_count:
        return quality

    indices = [
        round(i * (len(quality) - 1) / (sample_count - 1))
        for i in range(sample_count)
    ]
    picked: list[str] = []
    seen: set[int] = set()
    for idx in indices:
        if idx in seen:
            continue
        seen.add(idx)
        picked.append(quality[idx])
    return picked


MIXED_ROOM_MARKERS = (
    "mixed",
    "unknown",
    "multiple",
    "various",
    "private area",
    "private quarters",
)


def _feature_set(space: SpaceInventoryItem) -> set[str]:
    return {str(f).lower().strip() for f in (space.features or []) if str(f).strip()}


def _spaces_similar(a: SpaceInventoryItem, b: SpaceInventoryItem, threshold: float = 0.28) -> bool:
    """Heuristic: same type + overlapping features ⇒ same physical room."""
    if _normalize_type(a.type) != _normalize_type(b.type):
        return False
    fa, fb = _feature_set(a), _feature_set(b)
    if not fa or not fb:
        return True
    return len(fa & fb) / max(len(fa | fb), 1) >= threshold


def finalize_space_inventory(segments: list[VKBSegment]) -> list[VKBSegment]:
    """Dedupe noisy / repeated spaces, then assign global display names."""
    sorted_segs = sorted(segments, key=lambda s: s.raw.start_time)

    established: list[tuple[str, float]] = []  # (room_type, end_time)
    for seg in sorted_segs:
        spaces = seg.knowledge.spaces or []
        room = _normalize_type(seg.knowledge.room_type or "")
        if room and room not in ("Mixed Private Area", "Unknown") and len(spaces) <= 1:
            established.append((room, float(seg.raw.end_time)))

    for seg in sorted_segs:
        spaces = list(seg.knowledge.spaces or [])
        if len(spaces) <= 1:
            continue
        primary = _normalize_type(seg.knowledge.room_type or "")
        filtered: list[SpaceInventoryItem] = []
        for space in spaces:
            st = _normalize_type(space.type)
            if st in ("Mixed Private Area", "Unknown"):
                continue
            # Drop public-room echoes only when an earlier dedicated segment
            # already owned that room AND this segment's primary is different.
            earlier = any(
                er == st and end_t <= float(seg.raw.start_time) + 0.01
                for er, end_t in established
            )
            if earlier and st in ("Kitchen", "Living Room", "Dining Room") and primary != st:
                logger.info(
                    "Dropping %s echo from %s (already established earlier)",
                    st,
                    seg.segment_id,
                )
                continue
            filtered.append(space)
        if filtered:
            seg.knowledge.spaces = filtered

    # Drop hallucinated Bathroom (and speculative door-guess rooms) before dedupe.
    for seg in sorted_segs:
        kept_spaces: list[SpaceInventoryItem] = []
        for space in list(seg.knowledge.spaces or []):
            st = _normalize_type(space.type)
            feats = list(space.features or [])
            if st == "Bathroom" and not bathroom_space_is_grounded(space):
                logger.info(
                    "Dropping ungrounded Bathroom from %s (no fixture evidence): %s",
                    seg.segment_id,
                    feats[:2],
                )
                continue
            # Bedroom / Bathroom invented solely from "likely … doors" speculation
            if feats and all(_is_speculative_phrase(f) for f in feats):
                if st in ("Bathroom", "Bedroom"):
                    logger.info(
                        "Dropping speculative %s from %s: %s",
                        st,
                        seg.segment_id,
                        feats[:1],
                    )
                    continue
            kept_spaces.append(space)
        if kept_spaces or not (seg.knowledge.spaces or []):
            seg.knowledge.spaces = kept_spaces

    seen: list[SpaceInventoryItem] = []
    for seg in sorted_segs:
        kept: list[SpaceInventoryItem] = []
        for space in list(seg.knowledge.spaces or []):
            space.type = _normalize_type(space.type)
            match = next((s for s in seen if _spaces_similar(s, space)), None)
            if match is not None:
                logger.info(
                    "Merging duplicate %s in %s into earlier instance",
                    space.type,
                    seg.segment_id,
                )
                kept.append(
                    SpaceInventoryItem(
                        type=match.type,
                        instance=match.instance,
                        instance_id=match.instance_id or _instance_id(match.type, match.instance),
                        confidence=max(match.confidence, space.confidence),
                        features=list(dict.fromkeys(list(match.features) + list(space.features))),
                        display_name=match.display_name,
                        narration_name=match.narration_name,
                        room_role=match.room_role,
                    )
                )
                match.features = list(dict.fromkeys(list(match.features) + list(space.features)))
                match.confidence = max(match.confidence, space.confidence)
            else:
                kept.append(space)
                seen.append(space)
        seg.knowledge.spaces = kept

    segments = renumber_property_spaces(segments)

    # Verified Space Layer: fixture gates + Module-4 conflict resolver
    from backend.agents.vision.modules.space_evidence_validator import validate_segment_spaces

    for seg in segments:
        validate_segment_spaces(seg)

    # Re-number after rejects may have removed spaces
    segments = renumber_property_spaces(segments)

    from backend.workflows.room_naming import normalize_segment_spaces

    return normalize_segment_spaces(segments)


def renumber_property_spaces(segments: list[VKBSegment]) -> list[VKBSegment]:
    """Assign globally unique instance numbers for distinct physical spaces."""
    type_counters: dict[str, int] = {}
    unique_spaces: list[SpaceInventoryItem] = []

    for seg in sorted(segments, key=lambda s: s.raw.start_time):
        for space in seg.knowledge.spaces or []:
            space.type = _normalize_type(space.type)
            match = next((u for u in unique_spaces if _spaces_similar(u, space)), None)
            if match is not None:
                space.instance = match.instance
                space.instance_id = match.instance_id
                space.display_name = match.display_name
                space.type = match.type
                # Preserve evidence features on both copies
                merged = list(dict.fromkeys(list(match.features or []) + list(space.features or [])))
                match.features = merged
                space.features = merged
                continue
            type_counters[space.type] = type_counters.get(space.type, 0) + 1
            space.instance = type_counters[space.type]
            space.instance_id = _instance_id(space.type, space.instance)
            unique_spaces.append(space)

    type_totals = dict(type_counters)
    for space in unique_spaces:
        space.instance_id = _instance_id(space.type, space.instance)
        space.display_name = _display_name(space.type, space.instance, type_totals)

    for seg in segments:
        for space in seg.knowledge.spaces or []:
            match = next((u for u in unique_spaces if _spaces_similar(u, space)), None)
            if match is not None:
                space.instance = match.instance
                space.instance_id = match.instance_id
                space.display_name = match.display_name
                space.type = match.type
                space.features = list(dict.fromkeys(list(match.features or []) + list(space.features or [])))

    return segments


def should_reanalyze(
    segment: VKBSegment,
    duration_threshold: float = DEFAULT_DURATION_THRESHOLD,
    confidence_trigger: float = DEFAULT_CONFIDENCE_TRIGGER,
) -> bool:
    """Trigger inventory without changing CLIP boundaries.

    Conditions (any):
    - duration > threshold
    - room_type is Mixed / Unknown
    - confidence < trigger
    - Module-4 facts conflict with primary room_type (e.g. Kitchen + shower)
    """
    duration = float(segment.raw.duration or (segment.raw.end_time - segment.raw.start_time))
    if duration > duration_threshold:
        return True

    room = (segment.knowledge.room_type or "").lower()
    if any(marker in room for marker in MIXED_ROOM_MARKERS):
        return True

    conf = float(segment.knowledge.confidence or segment.confidence or 0.0)
    if conf < confidence_trigger:
        return True

    if has_room_evidence_conflict(segment.knowledge):
        return True

    return False


class LongSegmentAnalyzer:
    """Re-analyze long / mixed / conflicting segments to recover multi-space inventories."""

    def __init__(
        self,
        llm_provider: Any | None = None,
        duration_threshold: float = DEFAULT_DURATION_THRESHOLD,
        sample_count: int = DEFAULT_SAMPLE_COUNT,
        confidence_trigger: float = DEFAULT_CONFIDENCE_TRIGGER,
    ) -> None:
        self.llm_provider = llm_provider
        self.duration_threshold = duration_threshold
        self.sample_count = sample_count
        self.confidence_trigger = confidence_trigger

    def _ensure_provider(self) -> Any:
        if self.llm_provider is not None:
            return self.llm_provider
        from backend.services.llm.openai_provider import OpenAIProvider

        self.llm_provider = OpenAIProvider()
        return self.llm_provider

    def _parse_spaces(self, content: str) -> list[SpaceInventoryItem]:
        text = (content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                return []
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return []

        raw_spaces = data.get("spaces") if isinstance(data, dict) else data
        if not isinstance(raw_spaces, list):
            return []

        items: list[SpaceInventoryItem] = []
        for entry in raw_spaces:
            if isinstance(entry, str):
                items.append(SpaceInventoryItem(type=_normalize_type(entry), confidence=0.7))
                continue
            if not isinstance(entry, dict):
                continue
            space_type = entry.get("type") or entry.get("room") or entry.get("room_type") or ""
            features = entry.get("features") or entry.get("evidence") or []
            if isinstance(features, str):
                features = [features]
            items.append(
                SpaceInventoryItem(
                    type=_normalize_type(str(space_type)),
                    confidence=float(entry.get("confidence", 0.75) or 0.75),
                    features=[str(f) for f in features if f],
                )
            )
        return assign_instances(items)

    async def inventory_frames(self, image_paths: list[str]) -> list[SpaceInventoryItem]:
        quality_paths = filter_quality_frames(image_paths)
        if not quality_paths:
            quality_paths = list(image_paths)
        if not quality_paths:
            return []

        provider = self._ensure_provider()
        instruction = (
            "These frames are sampled across ONE continuous video segment of a property walkthrough.\n"
            "Identify ALL unique spaces shown. A space should be included if it is clearly visible, "
            "even if briefly appears.\n"
            "If both Kitchen and Bathroom appear, list both with evidence features "
            "(cooktop / toilet / shower / etc.).\n"
            "Ignore black frames and end-title / logo screens.\n"
            "Return ONLY the JSON object with spaces[{type, confidence, features}]."
        )

        try:
            from backend.services.llm.openai_provider import OpenAIProvider

            if isinstance(provider, OpenAIProvider):
                response = await provider.generate_vision(
                    system_prompt=INVENTORY_SYSTEM_PROMPT,
                    text_content=instruction,
                    image_paths=quality_paths,
                    temperature=0.1,
                    max_tokens=2048,
                )
                return self._parse_spaces(response.content)

            logger.warning("LongSegmentAnalyzer requires OpenAIProvider.generate_vision")
            return []
        except Exception as exc:
            logger.error("Long segment inventory failed: %s", exc, exc_info=True)
            return []

    async def enrich_segments(
        self,
        segments: list[VKBSegment],
        frames: list[dict[str, Any]] | None = None,
    ) -> list[VKBSegment]:
        """Attach spaces inventory to every segment; re-analyze when triggered."""
        frames = frames or []
        for seg in segments:
            duration = float(seg.raw.duration or (seg.raw.end_time - seg.raw.start_time))
            if should_reanalyze(seg, self.duration_threshold, self.confidence_trigger):
                sample_paths = select_sample_frames(
                    frames,
                    start_time=seg.raw.start_time,
                    end_time=seg.raw.end_time,
                    sample_count=self.sample_count,
                    fallback_keyframes=list(seg.raw.keyframes or []),
                )
                logger.info(
                    "Space inventory re-analysis %s (%.1fs, room=%s, conf=%.2f, frames=%d)",
                    seg.segment_id,
                    duration,
                    seg.knowledge.room_type,
                    float(seg.knowledge.confidence or 0),
                    len(sample_paths),
                )
                spaces = await self.inventory_frames(sample_paths)
                if not spaces:
                    spaces = spaces_from_primary(seg.knowledge)
                # Always merge Module-4 evidence so Bathroom isn't dropped when
                # inventory collapses to the dominant Kitchen label.
                spaces = merge_evidence_into_spaces(spaces, seg.knowledge)

                seg.knowledge.spaces = spaces
                # Keep Module-4 primary unless multiple distinct spaces found.
                if len({s.type for s in spaces if s.type not in ("Unknown",)}) > 1:
                    if has_room_evidence_conflict(seg.knowledge) or len(spaces) > 1:
                        # Preserve original primary in notes for debugging
                        if seg.knowledge.notes and "primary=" not in seg.knowledge.notes:
                            seg.knowledge.notes = (
                                f"{seg.knowledge.notes}; primary={seg.knowledge.room_type}"
                            ).strip("; ")
                        elif not seg.knowledge.notes:
                            seg.knowledge.notes = f"primary={seg.knowledge.room_type}"
                        seg.knowledge.room_type = "Mixed Private Area"
                logger.info(
                    "  %s spaces: %s",
                    seg.segment_id,
                    [
                        f"{s.display_name or s.type}"
                        + (f"[{','.join(s.features[:3])}]" if s.features else "")
                        for s in spaces
                    ],
                )
            else:
                if not seg.knowledge.spaces:
                    spaces = spaces_from_primary(seg.knowledge)
                    if has_room_evidence_conflict(seg.knowledge):
                        spaces = merge_evidence_into_spaces(spaces, seg.knowledge)
                    seg.knowledge.spaces = spaces

        return finalize_space_inventory(segments)
