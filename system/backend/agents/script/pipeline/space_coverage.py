"""Space Coverage Controller — Narration Planner + Coverage Checker.

Planner decides WHICH spaces deserve attention. This layer decides HOW
they appear in a single spoken sentence:

  main_space (hero) + secondary_spaces (support, mention_required)
  optional spaces may be omitted for pacing.

Hero Score = Evidence Confidence × Marketing Value
(Verified Space Layer evidence beats marketing-only bias.)

Does NOT emit one sentence per room — keeps cinematic one-liner coverage.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.schemas.vision_schema import SpaceInventoryItem, VKBSegment, VisionKnowledgeBase
from backend.workflows.room_naming import narration_label

logger = logging.getLogger(__name__)

HERO_TYPES = frozenset({
    "Living Room", "Kitchen", "Primary Bedroom", "Dining Room",
})
SUPPORT_TYPES = frozenset({
    "Bathroom", "Study Area", "Study Room", "Balcony", "Secondary Bedroom",
    "Bedroom Area", "Bedroom", "Guest Bedroom", "Laundry", "Laundry Room",
})
OPTIONAL_TYPES = frozenset({
    "Hallway", "Closet", "Corridor", "Unknown", "Mixed Private Area",
})

SPACE_MENTION_CUES: dict[str, tuple[str, ...]] = {
    "Bathroom": (
        "bathroom", "toilet", "shower", "vanity", "卫浴", "卫生间", "浴室",
        "淋浴", "马桶", "洗手台",
    ),
    "Kitchen": ("kitchen", "cooktop", "stove", "sink", "counter", "厨房", "灶", "水槽", "台面", "橱柜"),
    "Living Room": ("living", "sofa", "客厅", "沙发"),
    "Dining Room": ("dining", "餐厅"),
    "Study Area": ("study", "desk", "书房", "书桌", "办公"),
    "Study Room": ("study", "desk", "书房", "书桌", "办公"),
    "Primary Bedroom": ("primary bedroom", "master bedroom", "主卧"),
    "Secondary Bedroom": ("bedroom", "次卧", "卧室"),
    "Bedroom Area": ("bedroom", "卧室", "床"),
    "Bedroom": ("bedroom", "卧室", "床"),
    "Guest Bedroom": ("guest", "客卧", "客房"),
    "Hallway": ("hallway", "corridor", "走廊", "过道"),
    "Balcony": ("balcony", "阳台", "露台"),
    "Laundry": ("laundry", "洗衣"),
    "Laundry Room": ("laundry", "洗衣"),
    "Closet": ("closet", "wardrobe", "衣帽", "衣柜"),
}


class CoverageSpace(BaseModel):
    type: str = ""
    narration_name: str = ""
    instance_id: str = ""
    priority: float = 0.5
    importance: str = "support"
    coverage: str = "required"
    role: str = "support"
    room_role: str = ""  # primary / secondary / glimpse (from Verified Space Layer)
    mention_required: bool = False
    features: list[str] = Field(default_factory=list)
    evidence_score: float = 0.0
    hero_score: float = 0.0
    verified: bool = True


class SegmentCoveragePlan(BaseModel):
    segment_id: str = ""
    narration_goal: str = ""
    narration_mode: str = "detail"
    main_space: Optional[CoverageSpace] = None
    secondary_spaces: list[CoverageSpace] = Field(default_factory=list)
    optional_spaces: list[CoverageSpace] = Field(default_factory=list)
    must_mention: list[str] = Field(default_factory=list)
    spaces: list[CoverageSpace] = Field(default_factory=list)


class CoverageCheckResult(BaseModel):
    coverage_failed: bool = False
    missing_by_segment: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def missing_segment_ids(self) -> list[str]:
        return list(self.missing_by_segment.keys())


def _tier_for(name: str, space_type: str, room_role: str) -> str:
    key = (name or space_type or "").strip()
    if room_role == "glimpse":
        # Seen through a doorway / in passing — never required in THIS segment.
        # Tour-level coverage may still promote it in its strongest segment.
        return "optional"
    if room_role == "primary" or key == "Primary Bedroom":
        return "hero"
    if key in HERO_TYPES or space_type in HERO_TYPES:
        return "hero"
    if key in OPTIONAL_TYPES or space_type in OPTIONAL_TYPES:
        return "optional"
    if key in SUPPORT_TYPES or space_type in SUPPORT_TYPES:
        return "support"
    if key and key not in ("Mixed Private Area", "Unknown"):
        return "support"
    return "optional"


def _camera_is_there(space: CoverageSpace, main: Optional[CoverageSpace]) -> bool:
    """True when this space is on-camera enough to name in the current sentence.

    Utility rooms (laundry, study) glimpsed from a living area must wait until
    they are the shot's main space — otherwise TTS says "洗衣区" while the
    sofa is still filling the frame.
    """
    if space.room_role == "glimpse":
        return False
    name = (space.narration_name or space.type or "").strip()
    stype = (space.type or "").strip()
    main_name = (main.narration_name or main.type or "") if main else ""
    main_type = (main.type or "") if main else ""
    if name in {"Study Area", "Study Room"} or stype in {"Study Room", "Study Area"}:
        return main_type in {"Study Room", "Study Area"} or main_name in {"Study Area", "Study Room"}
    if name in {"Laundry", "Laundry Room"} or stype in {"Laundry Room", "Laundry"}:
        return main_type in {"Laundry Room", "Laundry"} or main_name in {"Laundry", "Laundry Room"}
    if name == "Bathroom" or stype == "Bathroom":
        # Ensuite / kitchen-bath hybrid is on camera; hallway/living approach is not.
        return main_type in {"Bathroom", "Kitchen"} or main_name in {"Bathroom", "Kitchen"}
    return True


def _priority_for(tier: str, confidence: float, segment_role: str) -> float:
    base = {"hero": 0.9, "support": 0.65, "optional": 0.35}.get(tier, 0.5)
    if segment_role == "HERO" and tier == "hero":
        base = min(1.0, base + 0.05)
    return round(min(1.0, base * 0.7 + float(confidence or 0.5) * 0.3), 3)


def _space_to_coverage(
    space: SpaceInventoryItem,
    *,
    segment_role: str,
) -> CoverageSpace:
    from backend.agents.vision.modules.space_evidence_validator import hero_score

    name = narration_label(space) or space.type or "Room"
    tier = _tier_for(name, space.type, space.room_role)
    ev = getattr(space, "evidence", None)
    ev_score = float(getattr(ev, "evidence_score", 0.0) or 0.0) if ev else 0.0
    verified = bool(getattr(ev, "verified", True)) if ev else True
    h_score = hero_score(space)
    if not verified or (space.type in ("Kitchen", "Bathroom") and not verified):
        tier = "optional"
    required = tier in ("hero", "support")
    return CoverageSpace(
        type=space.type or name,
        narration_name=name,
        instance_id=space.instance_id or "",
        room_role=space.room_role or "",
        priority=max(_priority_for(tier, space.confidence, segment_role), h_score),
        importance=tier,
        coverage="required" if required else "optional",
        role=tier,
        mention_required=required,
        features=list((space.features or [])[:4]),
        evidence_score=ev_score,
        hero_score=h_score,
        verified=verified,
    )


def _dedupe_by_name(items: list[CoverageSpace]) -> list[CoverageSpace]:
    seen: set[str] = set()
    out: list[CoverageSpace] = []
    for item in sorted(items, key=lambda s: (-s.hero_score, -s.priority, s.narration_name)):
        key = (item.narration_name or item.type).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def build_segment_coverage_plan(
    segment: VKBSegment,
    *,
    segment_role: str = "SUPPORT",
    narrative_function: str = "",
    video_duration: float = 0.0,
) -> SegmentCoveragePlan:
    """Hero = argmax(Evidence × Marketing), not marketing alone."""
    raw_spaces = [
        _space_to_coverage(s, segment_role=segment_role)
        for s in (segment.knowledge.spaces or [])
        if narration_label(s) or s.type
    ]
    raw_spaces = [
        s for s in raw_spaces
        if not (s.type in ("Kitchen", "Bathroom") and not s.verified)
    ]
    spaces = _dedupe_by_name(raw_spaces)

    forced: set[str] = set()
    nf = (narrative_function or "").lower()
    if "cover spaces:" in nf:
        tail = narrative_function.split("cover spaces:", 1)[-1]
        for part in re.split(r"[,|/]| and ", tail):
            label = part.strip(" .;|")
            if label and len(label) < 40:
                forced.add(label.lower())
    if "summarize private spaces" in nf:
        mode = "summary"
    else:
        mode = "summary" if (video_duration and video_duration <= 45 and len(spaces) >= 3) else "detail"

    for sp in spaces:
        if sp.narration_name.lower() in forced or sp.type.lower() in forced:
            if sp.narration_name in OPTIONAL_TYPES or sp.type in OPTIONAL_TYPES:
                continue
            if sp.type in ("Kitchen", "Bathroom") and not sp.verified:
                continue
            if sp.room_role == "glimpse":
                # Planner may ask to cover this space, but here it is only
                # glimpsed — tour-level coverage will place it in the segment
                # where the camera actually shows it.
                continue
            sp.coverage = "required"
            sp.mention_required = True
            if sp.importance == "optional":
                sp.importance = "support"
                sp.role = "support"

    ranked = sorted(spaces, key=lambda s: (-s.hero_score, -s.priority))
    main: Optional[CoverageSpace] = None
    secondary: list[CoverageSpace] = []
    optionals: list[CoverageSpace] = [s for s in spaces if s.importance == "optional"]

    if ranked:
        main = ranked[0]
        main.role = "hero"
        main.mention_required = True
        main.importance = "hero"
        for s in ranked[1:]:
            forced_here = (
                s.narration_name.lower() in forced
                and s.room_role != "glimpse"
                and s.narration_name not in OPTIONAL_TYPES
                and s.type not in OPTIONAL_TYPES
            )
            if s.importance == "optional" and not forced_here:
                if s not in optionals:
                    optionals.append(s)
            else:
                secondary.append(s)

    FACILITY_BOOST = {
        "Bathroom": 0, "Balcony": 1, "Laundry": 2, "Laundry Room": 2,
        "Kitchen": 3, "Dining Room": 4, "Study Area": 5, "Study Room": 5,
        "Secondary Bedroom": 6, "Bedroom Area": 6, "Bedroom": 6, "Guest Bedroom": 6,
    }
    secondary = sorted(
        secondary,
        key=lambda s: (FACILITY_BOOST.get(s.narration_name, 9), -s.hero_score, -s.priority),
    )
    max_support = 2 if mode == "detail" else 1
    kept_secondary: list[CoverageSpace] = []
    for i, s in enumerate(secondary):
        s.role = "support"
        protect = s.narration_name in {
            "Bathroom", "Kitchen", "Balcony", "Living Room",
        } or s.type in {"Bathroom", "Kitchen", "Balcony"}
        on_camera = _camera_is_there(s, main)
        if not on_camera:
            s.mention_required = False
            s.coverage = "optional"
            optionals.append(s)
            continue
        if i < max_support or protect or (s.narration_name.lower() in forced):
            s.mention_required = True
            s.coverage = "required"
            kept_secondary.append(s)
        else:
            s.mention_required = False
            s.coverage = "optional"
            optionals.append(s)
    secondary = kept_secondary

    protect_names = {"Bathroom", "Kitchen", "Balcony", "Laundry", "Laundry Room", "Living Room"}
    if mode == "summary":
        trimmed: list[CoverageSpace] = []
        for s in secondary:
            if s.narration_name in protect_names or s.type in protect_names:
                trimmed.append(s)
            elif "bedroom" in (s.narration_name or "").lower() or "study" in (s.narration_name or "").lower():
                s.coverage = "optional"
                s.mention_required = False
                optionals.append(s)
            else:
                trimmed.append(s)
        secondary = trimmed

    # Hard cap: one spoken sentence can carry the main space + 2 supports at
    # most. Extra rooms become optional here; the tour-level guarantee will
    # re-place any space that ends up unspoken across the whole video.
    MAX_REQUIRED_SUPPORT = 2
    required_kept: list[CoverageSpace] = []
    overflow: list[CoverageSpace] = []
    for s in secondary:
        if s.mention_required and len(required_kept) >= MAX_REQUIRED_SUPPORT:
            s.mention_required = False
            s.coverage = "optional"
            overflow.append(s)
        elif s.mention_required:
            required_kept.append(s)
    if overflow:
        secondary = [s for s in secondary if s not in overflow]
        optionals.extend(overflow)

    must_mention: list[str] = []
    if main and main.mention_required:
        must_mention.append(main.narration_name)
    for s in secondary:
        if s.mention_required and s.narration_name not in must_mention:
            must_mention.append(s.narration_name)

    goal = (narrative_function or "").split("|")[0].strip() or "highlight functional areas"
    return SegmentCoveragePlan(
        segment_id=segment.segment_id,
        narration_goal=goal[:120],
        narration_mode=mode,
        main_space=main,
        secondary_spaces=secondary,
        optional_spaces=optionals,
        must_mention=must_mention,
        spaces=spaces,
    )


def build_coverage_plans(
    vkb: VisionKnowledgeBase,
    planning: dict[str, Any] | None = None,
) -> dict[str, SegmentCoveragePlan]:
    planning = planning or {}
    role_by_id = {
        str(a.get("segment_id", "")): str(a.get("role", "SUPPORT")) or "SUPPORT"
        for a in planning.get("attention_map", [])
    }
    narrative_by_id = {
        str(n.get("segment_id", "")): n for n in planning.get("narrative_flow", [])
    }
    duration = float(getattr(vkb.video, "duration", 0.0) or 0.0)
    plans: dict[str, SegmentCoveragePlan] = {}
    for seg in sorted(vkb.segments, key=lambda s: s.raw.start_time):
        narrative = narrative_by_id.get(seg.segment_id, {})
        plan = build_segment_coverage_plan(
            seg,
            segment_role=role_by_id.get(seg.segment_id, "SUPPORT"),
            narrative_function=str(narrative.get("narrative_function", "")),
            video_duration=duration,
        )
        plans[seg.segment_id] = plan
        logger.info(
            "Coverage plan %s: main=%s hero=%.2f must=%s secondary=%s",
            seg.segment_id,
            plan.main_space.narration_name if plan.main_space else "-",
            plan.main_space.hero_score if plan.main_space else 0.0,
            plan.must_mention,
            [s.narration_name for s in plan.secondary_spaces],
        )
    _guarantee_tour_coverage(plans)
    return plans


def _guarantee_tour_coverage(plans: dict[str, SegmentCoveragePlan]) -> None:
    """Every verified real space must be spoken SOMEWHERE in the tour.

    Per-segment demotion (glimpse → optional) prevents cross-room prose, but
    could silently drop a space from the whole video. This pass promotes each
    uncovered space back to must_mention in the ONE segment where its
    evidence is strongest — coverage without narrating rooms off-camera.
    """
    covered: set[str] = set()
    for plan in plans.values():
        covered.update(n.lower() for n in plan.must_mention)

    # name -> (best score, segment_id, space) among segments where this
    # space is already the shot's main room (camera is actually there).
    best: dict[str, tuple[float, str, CoverageSpace]] = {}
    for seg_id, plan in plans.items():
        main_name = (plan.main_space.narration_name or plan.main_space.type) if plan.main_space else ""
        for sp in plan.spaces:
            name = (sp.narration_name or sp.type).strip()
            if not name or name.lower() in covered:
                continue
            if not sp.verified:
                continue
            if name in OPTIONAL_TYPES or sp.type in OPTIONAL_TYPES:
                continue
            if not _camera_is_there(sp, plan.main_space) and name.lower() != main_name.lower():
                continue
            score = max(sp.hero_score, sp.evidence_score, sp.priority)
            prev = best.get(name.lower())
            if prev is None or score > prev[0]:
                best[name.lower()] = (score, seg_id, sp)

    for name_key, (score, seg_id, sp) in best.items():
        plan = plans[seg_id]
        sp.mention_required = True
        sp.coverage = "required"
        if sp.importance == "optional":
            sp.importance = "support"
            sp.role = "support"
        if sp.narration_name not in plan.must_mention:
            plan.must_mention.append(sp.narration_name)
        if sp not in plan.secondary_spaces and sp is not plan.main_space:
            plan.secondary_spaces.append(sp)
            plan.optional_spaces = [o for o in plan.optional_spaces if o is not sp]
        logger.info(
            "Tour coverage: promoted %s into %s (score=%.2f) so it is not skipped",
            sp.narration_name, seg_id, score,
        )


def space_mentioned(text: str, narration_name: str) -> bool:
    if not text or not narration_name:
        return False
    low = text.lower()
    cues = SPACE_MENTION_CUES.get(narration_name)
    if cues and any(c.lower() in low for c in cues):
        return True
    if narration_name.lower() in low:
        return True
    zh_map = {
        "Bathroom": "卫生",
        "Kitchen": "厨",
        "Living Room": "客厅",
        "Study Area": "书房",
        "Primary Bedroom": "主卧",
        "Balcony": "阳台",
        "Bedroom Area": "卧室",
        "Bedroom": "卧室",
    }
    tip = zh_map.get(narration_name)
    return bool(tip and tip in text)


def check_coverage(
    texts: dict[str, str],
    plans: dict[str, SegmentCoveragePlan],
) -> CoverageCheckResult:
    missing: dict[str, list[str]] = {}
    for seg_id, plan in plans.items():
        text = texts.get(seg_id, "") or ""
        absent = [name for name in plan.must_mention if not space_mentioned(text, name)]
        if absent:
            missing[seg_id] = absent
    failed = bool(missing)
    if failed:
        logger.warning("Coverage check failed: %s", missing)
    else:
        logger.info("Coverage check passed for %d segments", len(plans))
    return CoverageCheckResult(coverage_failed=failed, missing_by_segment=missing)


def plan_to_prompt_dict(plan: SegmentCoveragePlan) -> dict[str, Any]:
    main = plan.main_space
    return {
        "narration_goal": plan.narration_goal,
        "narration_mode": plan.narration_mode,
        "main_space": (
            {
                "type": main.narration_name,
                "role": "hero",
                "features": main.features[:3],
                "hero_score": main.hero_score,
            }
            if main
            else None
        ),
        "secondary_spaces": [
            {
                "type": s.narration_name,
                "role": "support",
                "mention_required": True,
                "features": s.features[:2],
            }
            for s in plan.secondary_spaces
            if s.mention_required
        ],
        "must_mention": plan.must_mention,
        "coverage_note": (
            "Name only rooms the camera is in now. Do not say 书房/客卧/主卧/次卧 "
            "unless that exact label is in must_mention. Do not use 'X旁的Y' "
            "unless the previous scene's main_space is X and this cut is continuous. "
            "客卧 requires a bed; a sofa is 客厅. Without ensuite/walk-in/king, "
            "a bedroom is just 卧室."
        ),
    }
