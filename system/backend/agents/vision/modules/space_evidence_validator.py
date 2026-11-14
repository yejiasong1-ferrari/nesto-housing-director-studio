"""Verified Space Layer — Space Evidence Validation.

Runs after Vision Module 4 + Module 6 inventory, before Planner/Script.

Goals:
  - Attach hard/soft/negative evidence to each SpaceInventoryItem
  - Fixture gates: Bathroom / Kitchen cannot enter VKB on soft cues alone
  - Conflict resolver: Module-4 hard furniture beats Module-6 semantic guesses
  - Produce a Verified VKB that downstream agents may trust

Hard fixtures > furniture/layout > LLM interpretation.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

from backend.schemas.vision_schema import (
    RoomKnowledge,
    SpaceEvidence,
    SpaceInventoryItem,
    VKBSegment,
    VisionKnowledgeBase,
)

logger = logging.getLogger(__name__)

# ── Fixture / feature lexicons ────────────────────────────────

HARD_FIXTURES: dict[str, tuple[str, ...]] = {
    "Bathroom": (
        "toilet", "shower", "bathtub", "bath tub", "bidet", "wc", "lavatory",
        "showerhead", "shower enclosure", "shower stall", "washroom",
    ),
    "Kitchen": (
        "cooktop", "stove", "oven", "range hood", "rangehood", "refrigerator",
        "fridge", "dishwasher", "kitchen sink", "gas cooktop", "gas stove",
        "rice cooker",  # strong residential kitchen cue when with counters
    ),
    "Bedroom": ("bed", "headboard", "mattress", "duvet", "bedding", "nightstand"),
    "Study Room": ("desk", "laptop", "bookshelf", "task lamp", "office chair"),
    "Living Room": ("sofa", "sectional", "coffee table", "tv", "lounge"),
    "Dining Room": ("dining table", "dining chairs"),
    "Balcony": ("balcony", "terrace", "railing"),
    "Laundry Room": ("washing machine", "clothes dryer", "washer/dryer", "washer-dryer", "laundry sink", "washer", "dryer"),
    "Hallway": ("hallway", "corridor", "doorway"),
}

SOFT_CUES: dict[str, tuple[str, ...]] = {
    "Bathroom": ("vanity", "mirror", "tile", "tiled", "bath fixture", "towel"),
    "Kitchen": (
        "cabinet", "cabinets", "countertop", "counter", "open shelf",
        "hanging pan", "hanging pans", "dish rack", "kettle",
    ),
    "Bedroom": ("curtain", "wardrobe", "pillow", "air vent", "bay window"),
    "Study Room": ("notebook", "chair", "lamp", "bookshelf"),
    "Living Room": ("floor lamp", "rug", "wall art", "curtain"),
    "Hallway": ("door", "doors", "tiled floor", "ceiling light"),
    "Balcony": ("glass door", "outdoor"),
}

# Features that contradict a claimed type (Module-4 / inventory).
NEGATIVE_FOR: dict[str, tuple[str, ...]] = {
    "Kitchen": ("bed", "headboard", "mattress", "duvet", "bedding", "wardrobe"),
    "Bathroom": ("bed", "cooktop", "stove", "sofa", "dining table"),
    "Bedroom": ("cooktop", "stove", "toilet", "shower enclosure", "range hood"),
    "Study Room": ("toilet", "cooktop", "shower"),
    "Laundry Room": (
        "dishwasher", "stove", "oven", "cooktop", "range hood", "kitchen sink",
    ),
    "Hallway": ("sofa", "bathtub", "toilet", "cooktop"),
}

_SPECULATIVE = re.compile(
    r"\b(likely|possibly|perhaps|appears to|seem(?:s)? to|may be|might be|"
    r"probably|potential(?:ly)?|behind (?:the )?door|leading to|"
    r"interior doors?|closed doors?)\b",
    re.IGNORECASE,
)

# Marketing prior for Hero Score (Phase 2) — evidence still dominates.
MARKETING_VALUE: dict[str, float] = {
    "Kitchen": 0.95,
    "Living Room": 0.92,
    "Primary Bedroom": 0.90,
    "Dining Room": 0.85,
    "Bathroom": 0.70,
    "Bedroom": 0.80,
    "Secondary Bedroom": 0.78,
    "Bedroom Area": 0.78,
    "Study Room": 0.72,
    "Study Area": 0.72,
    "Balcony": 0.75,
    "Hallway": 0.30,
    "Laundry Room": 0.55,
    "Closet": 0.40,
}


def _norm_type(label: str) -> str:
    text = (label or "").strip()
    if not text:
        return "Unknown"
    text = re.sub(r"\s+\d+$", "", text).strip()
    aliases = {
        "study": "Study Room",
        "study room": "Study Room",
        "home office": "Study Room",
        "bath": "Bathroom",
        "bathroom": "Bathroom",
        "washroom": "Bathroom",
        "kitchenette": "Kitchen",
        "guest bedroom": "Bedroom",
        "master bedroom": "Bedroom",
        "living": "Living Room",
    }
    key = text.lower()
    if key in aliases:
        return aliases[key]
    return " ".join(w.capitalize() if w.islower() else w for w in text.split())


def _blob(parts: Iterable[str]) -> str:
    return " ".join(str(p).lower() for p in parts if p)


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Match a fixture keyword without hitting compounds (washer ≠ dishwasher)."""
    kw = (keyword or "").strip().lower()
    blob = (text or "").lower()
    if not kw or not blob:
        return False
    if " " in kw or "/" in kw:
        return kw in blob
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", blob))


def _match_any(blob: str, keywords: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for kw in keywords:
        if _keyword_in_text(kw, blob):
            hits.append(kw)
    return hits


def _is_speculative(text: str) -> bool:
    return bool(_SPECULATIVE.search(text or ""))


def _knowledge_phrases(knowledge: RoomKnowledge) -> list[str]:
    out: list[str] = []
    for field in (
        knowledge.selling_points or [],
        knowledge.furniture or [],
        knowledge.appliances or [],
        [knowledge.notes] if knowledge.notes else [],
        [knowledge.room_type] if knowledge.room_type else [],
    ):
        for item in field:
            if item and not _is_speculative(str(item)):
                out.append(str(item))
    return out


def classify_evidence(
    space_type: str,
    features: list[str],
    module4_phrases: Optional[list[str]] = None,
) -> SpaceEvidence:
    """Split features into hard / soft / negative and score grounding."""
    st = _norm_type(space_type)
    feat_list = [str(f) for f in (features or []) if f and not _is_speculative(str(f))]
    m4 = [str(f) for f in (module4_phrases or []) if f and not _is_speculative(str(f))]
    combined = feat_list + m4
    blob = _blob(combined)

    hard_keys = HARD_FIXTURES.get(st, ())
    soft_keys = SOFT_CUES.get(st, ())
    neg_keys = NEGATIVE_FOR.get(st, ())

    hard = []
    soft = []
    for phrase in combined:
        low = phrase.lower()
        if any(_keyword_in_text(k, low) for k in hard_keys):
            hard.append(phrase)
        elif any(_keyword_in_text(k, low) for k in soft_keys):
            soft.append(phrase)

    # Negative: Module-4 / features that contradict the claimed type
    negative = []
    for phrase in combined:
        low = phrase.lower()
        if any(_keyword_in_text(k, low) for k in neg_keys):
            negative.append(phrase)

    hard = list(dict.fromkeys(hard))
    soft = list(dict.fromkeys(soft))
    negative = list(dict.fromkeys(negative))

    # Score: hard fixtures dominate; soft alone is weak; negatives punish
    score = 0.0
    if hard:
        score = min(1.0, 0.55 + 0.15 * len(hard))
    elif soft:
        score = min(0.45, 0.15 * len(soft))
    if negative:
        score = max(0.0, score - 0.25 * min(len(negative), 3))

    return SpaceEvidence(
        hard_features=hard,
        soft_features=soft,
        negative_features=negative,
        evidence_score=round(score, 3),
        verified=True,
        reject_reason="",
    )


def bathroom_gate(evidence: SpaceEvidence, features: list[str]) -> tuple[bool, str]:
    """Bathroom needs ≥1 hard fixture, or ≥2 soft bath cues without speculation."""
    if evidence.hard_features:
        return True, ""
    soft_bath = [
        f for f in evidence.soft_features
        if any(_keyword_in_text(k, f) for k in ("vanity", "mirror", "bath fixture", "towel"))
    ]
    # tiled alone is not enough (kitchens are tiled too)
    if len(soft_bath) >= 2:
        return True, ""
    blob = _blob(features)
    if "bathroom" in blob and _is_speculative(" ".join(features)):
        return False, "speculative_bathroom"
    return False, "no_bathroom_fixture"


def kitchen_gate(evidence: SpaceEvidence, module4_phrases: list[str]) -> tuple[bool, str]:
    """Kitchen needs a hard cooking fixture; cabinets/shelves alone fail."""
    if evidence.hard_features:
        # Reject when Module-4 clearly shows a bedroom and no kitchen hard in M4
        m4_blob = _blob(module4_phrases)
        m4_has_bed = any(_keyword_in_text(k, m4_blob) for k in HARD_FIXTURES["Bedroom"])
        m4_has_kitchen_hard = bool(_match_any(m4_blob, HARD_FIXTURES["Kitchen"]))
        if m4_has_bed and not m4_has_kitchen_hard and evidence.negative_features:
            # Inventory claimed cooktop but Module-4 only sees bed — hallucination
            inv_only_hard = [
                h for h in evidence.hard_features
                if h.lower() not in m4_blob and not any(
                    _keyword_in_text(k, h) for k in ("bed", "desk", "wardrobe", "window")
                )
            ]
            # If hard kitchen claims aren't reflected in Module-4 at all, distrust
            if inv_only_hard and not m4_has_kitchen_hard:
                return False, "kitchen_conflicts_module4_bedroom"
        return True, ""
    return False, "no_kitchen_fixture"


def laundry_gate(
    evidence: SpaceEvidence,
    features: list[str],
    module4_phrases: list[str],
) -> tuple[bool, str]:
    """Laundry needs a washer/dryer; a dishwasher is kitchen, not laundry."""
    blob = _blob(list(features or []) + list(module4_phrases or []))
    kitchen_fixture = bool(_match_any(
        blob, ("dishwasher", "stove", "oven", "cooktop", "range hood"),
    ))
    laundry_appliance = bool(evidence.hard_features) or bool(_match_any(
        blob,
        ("washing machine", "clothes dryer", "washer/dryer", "washer-dryer", "washer", "dryer"),
    ))
    if kitchen_fixture and not laundry_appliance:
        return False, "kitchen_fixture_not_laundry"
    if laundry_appliance:
        return True, ""
    return False, "no_laundry_appliance"


def passes_fixture_gate(
    space_type: str,
    evidence: SpaceEvidence,
    features: list[str],
    module4_phrases: list[str],
) -> tuple[bool, str]:
    st = _norm_type(space_type)
    if st == "Bathroom":
        return bathroom_gate(evidence, features)
    if st == "Kitchen":
        return kitchen_gate(evidence, module4_phrases)
    if st == "Laundry Room":
        return laundry_gate(evidence, features, module4_phrases)
    # Other rooms: need some positive evidence OR soft cues; reject pure speculation
    if evidence.hard_features or evidence.soft_features:
        if evidence.evidence_score <= 0 and evidence.negative_features:
            return False, "contradicted"
        return True, ""
    # Empty features with type only — keep with low score (primary fallback)
    return True, ""


def evidence_weight(space: SpaceInventoryItem) -> float:
    """Numeric weight for conflict resolution / hero scoring."""
    ev = space.evidence or SpaceEvidence()
    conf = float(space.confidence or 0.5)
    return round(ev.evidence_score * 0.7 + conf * 0.3, 3)


def marketing_value(space_type: str, narration_name: str = "") -> float:
    key = narration_name or space_type
    if key in MARKETING_VALUE:
        return MARKETING_VALUE[key]
    st = _norm_type(space_type)
    return MARKETING_VALUE.get(st, 0.55)


def hero_score(space: SpaceInventoryItem) -> float:
    """Hero Score = Evidence Confidence × Marketing Value."""
    ev = space.evidence or SpaceEvidence()
    if ev.reject_reason:
        return 0.0
    ev_conf = ev.evidence_score if ev.evidence_score > 0 else float(space.confidence or 0.3)
    return round(ev_conf * marketing_value(space.type, space.narration_name), 3)


def validate_space(
    space: SpaceInventoryItem,
    knowledge: RoomKnowledge,
) -> Optional[SpaceInventoryItem]:
    """Attach evidence + apply fixture gate. Returns None if rejected."""
    st = _norm_type(space.type)
    space.type = st
    m4 = _knowledge_phrases(knowledge)
    evidence = classify_evidence(st, list(space.features or []), m4)

    # Enrich hard features from Module-4 when they support this type
    m4_blob = _blob(m4)
    for kw in HARD_FIXTURES.get(st, ()):
        if _keyword_in_text(kw, m4_blob) and kw not in _blob(evidence.hard_features):
            # pull matching phrases
            for phrase in m4:
                if _keyword_in_text(kw, phrase) and phrase not in evidence.hard_features:
                    evidence.hard_features.append(phrase)
    evidence.hard_features = list(dict.fromkeys(evidence.hard_features))
    # Recompute score after enrichment
    if evidence.hard_features and evidence.evidence_score < 0.55:
        evidence.evidence_score = min(1.0, 0.55 + 0.12 * len(evidence.hard_features))

    ok, reason = passes_fixture_gate(st, evidence, list(space.features or []), m4)
    if not ok and st == "Laundry Room" and reason == "kitchen_fixture_not_laundry":
        # Dishwasher / kitchen sink mislabeled as laundry → treat as kitchen.
        space.type = "Kitchen"
        return validate_space(space, knowledge)
    if not ok:
        evidence.verified = False
        evidence.reject_reason = reason
        evidence.evidence_score = 0.0
        space.evidence = evidence
        logger.info(
            "Reject %s (gate=%s) features=%s m4_neg=%s",
            st,
            reason,
            (space.features or [])[:3],
            evidence.negative_features[:2],
        )
        return None

    evidence.verified = True
    evidence.reject_reason = ""
    space.evidence = evidence
    # Blend vision confidence with evidence score for downstream
    space.confidence = round(
        0.4 * float(space.confidence or 0.5) + 0.6 * evidence.evidence_score,
        3,
    )
    return space


def resolve_segment_conflicts(
    spaces: list[SpaceInventoryItem],
    knowledge: RoomKnowledge,
) -> list[SpaceInventoryItem]:
    """If Bedroom hard evidence outweighs unverified Kitchen, drop Kitchen, etc."""
    if len(spaces) <= 1:
        return spaces

    by_type = {_norm_type(s.type): s for s in spaces}
    bedroom = by_type.get("Bedroom")
    kitchen = by_type.get("Kitchen")
    study = by_type.get("Study Room")

    if bedroom and kitchen:
        bed_w = evidence_weight(bedroom)
        kit_w = evidence_weight(kitchen)
        # Strong bedroom + weak/soft kitchen → remove kitchen
        if bed_w >= 0.55 and kit_w < bed_w * 0.75:
            logger.info(
                "Conflict resolver: Bedroom(%.2f) beats Kitchen(%.2f) — drop Kitchen",
                bed_w,
                kit_w,
            )
            spaces = [s for s in spaces if _norm_type(s.type) != "Kitchen"]
            by_type.pop("Kitchen", None)

    # A desk in a bedroom/bath is furniture, not a dedicated study.
    if study and (bedroom or by_type.get("Bathroom")):
        other = bedroom or by_type.get("Bathroom")
        other_hard = bool(other and other.evidence and other.evidence.hard_features)
        study_only_desk = True
        if study.evidence and study.evidence.hard_features:
            blob = " ".join(study.evidence.hard_features).lower()
            study_only_desk = "bookshelf" not in blob and "bookcase" not in blob
        if other_hard and study_only_desk:
            logger.info(
                "Conflict resolver: drop Study beside %s (desk is in-room furniture)",
                _norm_type(other.type) if other else "room",
            )
            spaces = [s for s in spaces if _norm_type(s.type) != "Study Room"]
            by_type.pop("Study Room", None)

    # Prefer Module-4 primary when inventory is Mixed soup
    primary = _norm_type(knowledge.room_type or "")
    if primary in ("Bedroom", "Living Room", "Kitchen", "Study Room") and primary in {
        _norm_type(s.type) for s in spaces
    }:
        # boost primary confidence slightly
        for s in spaces:
            if _norm_type(s.type) == primary and s.evidence:
                s.evidence.evidence_score = min(1.0, s.evidence.evidence_score + 0.05)

    return spaces


# Below this evidence weight (and with no hard fixture), a space seen in an
# open-plan frame is treated as a "glimpse" — visible in passing, NOT the
# subject of the shot. Glimpses stay in the VKB for coverage accounting but
# must not drive narration for this segment.
GLIMPSE_WEIGHT = 0.45
# Segments shorter than this are walkthrough transitions: at most one
# secondary space keeps full status; the rest are glimpses.
SHORT_SEGMENT_SECONDS = 4.0
# Minimum weight for a primary space to override a "Mixed Private Area" label.
PRIMARY_MIN_WEIGHT = 0.40
# Corner laundry / closet must not steal the shot from a furnished living space.
_UTILITY_PRIMARY = frozenset({"Laundry Room", "Closet", "Storage Room / Utility Room"})
_LIVING_PRIMARY = frozenset({"Living Room", "Kitchen", "Bedroom", "Dining Room"})
_CIRCULATION = frozenset({"Hallway", "Corridor"})


def assign_space_roles(knowledge: RoomKnowledge, duration: float = 0.0) -> None:
    """Pick ONE primary space per segment; demote weak co-visible spaces.

    Open-plan walkthroughs put 4-6 verified spaces on a 5-second shot, which
    downstream turns into "narrating the master suite while the camera shows
    the kitchen". This pass gives every segment a stable answer to
    "what room is the camera actually in right now":

      primary   — the single space the shot is about
      secondary — genuinely co-visible, evidence-backed space
      glimpse   — seen through a doorway / in passing; do not narrate here
    """
    spaces = list(knowledge.spaces or [])
    if not spaces:
        return

    m4_primary = _norm_type(knowledge.room_type or "")
    scored: list[tuple[float, SpaceInventoryItem]] = []
    for s in spaces:
        w = evidence_weight(s)
        if _norm_type(s.type) == m4_primary:
            w += 0.10  # Module-4 saw this as the room the camera is in
        scored.append((w, s))
    scored.sort(key=lambda x: -x[0])

    primary_w, primary = scored[0]
    living_candidates = [
        (w, s) for w, s in scored if _norm_type(s.type) in _LIVING_PRIMARY
    ]
    if (
        _norm_type(primary.type) in _UTILITY_PRIMARY
        and living_candidates
        and living_candidates[0][0] >= GLIMPSE_WEIGHT
    ):
        logger.info(
            "Space roles: keep %s as primary over utility %s",
            _norm_type(living_candidates[0][1].type),
            _norm_type(primary.type),
        )
        primary_w, primary = living_candidates[0]
    if (
        _norm_type(primary.type) in _CIRCULATION
        and living_candidates
    ):
        living_w, living_s = living_candidates[0]
        shot_blob = _blob(
            list(knowledge.selling_points or [])
            + list(living_s.features or [])
        )
        looks_like_room = (
            _keyword_in_text("window", shot_blob)
            or _keyword_in_text("sofa", shot_blob)
            or "city view" in shot_blob
            or "floor-to-ceiling" in shot_blob
        )
        if looks_like_room:
            logger.info(
                "Space roles: keep %s as primary over circulation %s",
                _norm_type(living_s.type),
                _norm_type(primary.type),
            )
            primary_w, primary = max(living_w, 0.5), living_s
    primary.room_role = "primary"

    secondary_kept = 0
    max_secondary = 1 if (duration and duration < SHORT_SEGMENT_SECONDS) else 2
    for w, s in scored:
        if s is primary:
            continue
        has_hard = bool(s.evidence and s.evidence.hard_features)
        if w < GLIMPSE_WEIGHT and not has_hard:
            s.room_role = "glimpse"
        elif secondary_kept < max_secondary:
            s.room_role = "secondary"
            secondary_kept += 1
        else:
            s.room_role = "glimpse"

    # Give the segment a concrete primary room label instead of the
    # narration-hostile "Mixed Private Area" whenever the winner is grounded.
    primary_type = _norm_type(primary.type)
    if primary_type not in ("Unknown",) and primary_w >= PRIMARY_MIN_WEIGHT:
        knowledge.room_type = primary_type

    logger.info(
        "Space roles: primary=%s(%.2f) secondary=%s glimpse=%s",
        primary_type,
        primary_w,
        [_norm_type(s.type) for s in spaces if s.room_role == "secondary"],
        [_norm_type(s.type) for s in spaces if s.room_role == "glimpse"],
    )


def validate_segment_spaces(segment: VKBSegment) -> VKBSegment:
    """Validate all spaces on one segment in place."""
    knowledge = segment.knowledge
    validated: list[SpaceInventoryItem] = []
    for space in list(knowledge.spaces or []):
        kept = validate_space(space, knowledge)
        if kept is not None:
            validated.append(kept)
    validated = resolve_segment_conflicts(validated, knowledge)

    # If everything was rejected, fall back to Module-4 primary
    if not validated:
        primary = _norm_type(knowledge.room_type or "Unknown")
        if primary not in ("Unknown", "Mixed Private Area"):
            feats = list(
                dict.fromkeys(
                    list(knowledge.selling_points or [])[:3]
                    + list(knowledge.furniture or [])[:3]
                )
            )
            fallback = SpaceInventoryItem(type=primary, confidence=knowledge.confidence or 0.7, features=feats)
            kept = validate_space(fallback, knowledge)
            if kept is not None:
                validated = [kept]
            else:
                # Force primary with soft evidence only
                fallback.evidence = classify_evidence(primary, feats, _knowledge_phrases(knowledge))
                fallback.evidence.verified = True
                fallback.evidence.evidence_score = max(0.4, fallback.evidence.evidence_score)
                validated = [fallback]

    knowledge.spaces = validated
    # Refresh primary room_type when single verified space remains
    types = {_norm_type(s.type) for s in validated if s.type not in ("Unknown",)}
    if len(types) == 1:
        knowledge.room_type = next(iter(types))
    elif len(types) > 1 and knowledge.room_type not in ("Mixed Private Area",):
        # keep Mixed if multi-space verified
        if not any(t == knowledge.room_type for t in types):
            knowledge.room_type = "Mixed Private Area"

    # Assign primary/secondary/glimpse roles + concrete primary room label.
    try:
        duration = max(
            0.0,
            float(segment.raw.end_time or 0.0) - float(segment.raw.start_time or 0.0),
        )
    except Exception:
        duration = 0.0
    assign_space_roles(knowledge, duration)
    return segment


def validate_verified_vkb(vkb: VisionKnowledgeBase) -> VisionKnowledgeBase:
    """Run Verified Space Layer on entire VKB (idempotent)."""
    for seg in vkb.segments or []:
        validate_segment_spaces(seg)
    logger.info(
        "Verified Space Layer complete: %d segments",
        len(vkb.segments or []),
    )
    return vkb
