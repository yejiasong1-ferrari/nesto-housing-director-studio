"""Attention scoring — rule-only, intent-conditioned.

A_raw(s) = α·IntentMatch + β·Vision + γ·NarrativeImportance + δ·ObjectSaliency

With intent gating before contrastive normalization:
    if intent_match < threshold: score *= penalty_multiplier
"""

from __future__ import annotations

from backend.schemas.planning_schema import AttentionSignals, DirectorIntent, SegmentUnderstanding
from backend.schemas.vision_schema import VKBSegment, VisionKnowledgeBase
from backend.workflows.room_naming import narration_label

DEFAULT_WEIGHTS = {
    "intent": 0.35,
    "vision": 0.25,
    "narrative_importance": 0.25,
    "object_saliency": 0.15,
}

DEFAULT_INTENT_GATE_THRESHOLD = 0.40
DEFAULT_INTENT_PENALTY_MULTIPLIER = 0.30

LIGHTING_SCORES = {
    "excellent": 1.0,
    "good": 0.8,
    "fair": 0.6,
    "poor": 0.4,
}

PREMIUM_STYLE_KEYWORDS = {
    "modern", "contemporary", "minimalist", "luxury", "premium",
}

TAG_KEYWORD_MAP: dict[str, list[str]] = {
    "highlight_kitchen": ["kitchen", "studio", "kitchenette", "range", "refrigerator", "countertop"],
    "highlight_living_room": ["living", "studio", "open-plan", "sitting", "sofa", "open plan"],
    "highlight_bedroom": ["bedroom", "bed", "studio"],
    "highlight_bathroom": ["bathroom", "shower", "vanity", "tub"],
    "highlight_natural_light": ["window", "natural light", "daylight", "light"],
    "highlight_spaciousness": ["open", "open-plan", "space", "hardwood", "large window", "floor"],
    "highlight_closet": ["closet", "storage", "walk-in"],
    "premium_feel": ["hardwood", "island", "granite", "marble", "premium"],
    "warm_inviting": ["warm", "cozy", "rug", "natural light"],
    "warm_premium": ["warm", "hardwood", "natural light", "premium"],
    "premium_warm_tone": ["warm", "hardwood", "natural light"],
    "emphasize_space": ["open", "space", "hardwood", "large window"],
    "modern_style": ["modern", "contemporary", "minimalist"],
    "family_friendly": ["bedroom", "kitchen", "living", "family"],
    "avoid_commercial_tone": [],
    "avoid_commercial_style": [],
}


def _segment_text(segment: VKBSegment) -> str:
    knowledge = segment.knowledge
    space_labels = [
        narration_label(s)
        for s in (knowledge.spaces or [])
        if narration_label(s)
    ]
    return " ".join([
        knowledge.room_type,
        " ".join(space_labels),
        knowledge.style,
        knowledge.layout,
        knowledge.lighting,
        " ".join(knowledge.selling_points),
        " ".join(knowledge.furniture),
        " ".join(knowledge.appliances),
    ]).lower()


def match_intent_to_segment(intent: DirectorIntent, segment: VKBSegment) -> tuple[float, list[str]]:
    """Compute intent match score and matched intent reason tags."""
    tags = list(intent.intent_tags)
    primary = intent.intent_graph.primary.lower()
    if primary:
        tags.append(primary)

    if not tags:
        return 0.5, []

    combined = _segment_text(segment)
    matched_tags: list[str] = []
    matches = 0
    scorable_tags = 0

    for tag in tags:
        if tag.startswith("avoid_"):
            continue
        scorable_tags += 1
        keywords = TAG_KEYWORD_MAP.get(
            tag,
            [tag.replace("highlight_", "").replace("_", " ")],
        )
        if any(kw in combined for kw in keywords):
            matches += 1
            matched_tags.append(f"intent:{tag}")

    if scorable_tags == 0:
        return 0.5, []

    base = matches / scorable_tags
    score = max(0.0, min(1.0, 0.2 + base * 0.8))
    return round(score, 3), matched_tags


def compute_vision_score(segment: VKBSegment, vkb: VisionKnowledgeBase) -> float:
    """Compute V(s): vision quality from VKB segment confidence."""
    base = segment.confidence
    seg_attention = [
        c.score for c in vkb.candidate_attention
        if c.segment_id == segment.segment_id
    ]
    attention_boost = max(seg_attention) if seg_attention else 0.0
    selling_boost = min(len(segment.knowledge.selling_points) * 0.02, 0.10)
    return round(min(1.0, base * 0.7 + attention_boost * 0.2 + selling_boost), 3)


def compute_aesthetic_score(segment: VKBSegment) -> float:
    """Compute aesthetic saliency (diagnostic only, not in fusion formula)."""
    knowledge = segment.knowledge
    lighting = LIGHTING_SCORES.get(knowledge.lighting.lower(), 0.6)
    style_score = 0.7
    if any(kw in knowledge.style.lower() for kw in PREMIUM_STYLE_KEYWORDS):
        style_score = 0.9
    feature_score = min(len(knowledge.selling_points) / 8.0, 1.0)
    return round(lighting * 0.5 + style_score * 0.25 + feature_score * 0.25, 3)


def compute_object_saliency(
    intent: DirectorIntent,
    segment: VKBSegment,
    vkb: VisionKnowledgeBase,
) -> tuple[float, list[str]]:
    """Compute object saliency from VKB candidate attention aligned with intent."""
    candidates = [
        c for c in vkb.candidate_attention
        if c.segment_id == segment.segment_id
    ]
    if not candidates:
        return 0.0, []

    intent_keywords: set[str] = set()
    for tag in intent.intent_tags:
        if tag.startswith("avoid_"):
            continue
        intent_keywords.update(TAG_KEYWORD_MAP.get(tag, [tag.replace("highlight_", "")]))

    best_score = 0.0
    reasons: list[str] = []
    for cand in candidates:
        target_lower = cand.target.lower()
        intent_boost = 1.0
        if any(kw in target_lower for kw in intent_keywords if len(kw) > 2):
            intent_boost = 1.15
            reasons.append(f"object:intent_aligned:{cand.target[:40]}")
        score = min(1.0, cand.score * intent_boost)
        if score > best_score:
            best_score = score

    return round(best_score, 3), reasons[:2]


def fuse_attention(
    intent_match: float,
    vision_score: float,
    narrative_importance: float,
    object_saliency: float,
    aesthetic_score: float = 0.0,
    weights: dict[str, float] | None = None,
    gate_threshold: float = DEFAULT_INTENT_GATE_THRESHOLD,
    penalty_multiplier: float = DEFAULT_INTENT_PENALTY_MULTIPLIER,
) -> tuple[float, AttentionSignals]:
    """Fuse component scores with intent gating (raw score before normalization)."""
    w = weights or DEFAULT_WEIGHTS
    signals = AttentionSignals(
        intent_match=round(intent_match, 3),
        vision=round(vision_score, 3),
        narrative_importance=round(narrative_importance, 3),
        object_saliency=round(object_saliency, 3),
        aesthetic=round(aesthetic_score, 3),
    )
    score = (
        w["intent"] * intent_match
        + w["vision"] * vision_score
        + w["narrative_importance"] * narrative_importance
        + w["object_saliency"] * object_saliency
    )
    if intent_match < gate_threshold:
        score *= penalty_multiplier
    return round(min(1.0, score), 3), signals


def build_attention_reasons(
    intent_match: float,
    vision_score: float,
    narrative_importance: float,
    intent_reasons: list[str],
    object_reasons: list[str],
    gate_threshold: float = DEFAULT_INTENT_GATE_THRESHOLD,
) -> list[str]:
    """Build intent-first explainable reason tags."""
    reasons: list[str] = list(intent_reasons)
    reasons.extend(object_reasons)

    if intent_match >= gate_threshold:
        reasons.append("intent:strong_match")
    elif intent_match > 0:
        reasons.append("intent:weak_match")

    if vision_score >= 0.85:
        reasons.append("vision:high_confidence")
    elif vision_score >= 0.7:
        reasons.append("vision:good_quality")

    if narrative_importance >= 0.8:
        reasons.append("narrative:high_potential")
    elif narrative_importance >= 0.55:
        reasons.append("narrative:moderate_potential")

    if intent_match < gate_threshold:
        reasons.append("intent:gated_down")

    return list(dict.fromkeys(reasons)) or ["baseline:coverage"]


def narrative_importance_from_understanding(
    understanding: SegmentUnderstanding | None,
    fallback: float = 0.5,
) -> float:
    """Extract narrative importance from segment understanding."""
    if understanding is None:
        return fallback
    return understanding.narrative_potential
