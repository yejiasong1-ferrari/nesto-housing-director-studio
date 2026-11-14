"""Module 2: Segment Optimizer.

Evaluates merge candidates using a 5-factor weighted score.
Produces merge groups — lists of consecutive EnrichedSegments that should
be combined into one timeline segment.

Merge score factors and weights:
  semantic_similarity  30%  — same / related room type
  same_space           25%  — identical room_type string
  narrative_role       20%  — compatible roles (no HERO involved)
  visual_continuity    15%  — consecutive segments only
  importance_factor    10%  — lower importance = safer to merge

VETO rules (score overridden to 0):
  - Either segment is HERO  → never merge (hero deserves its own window)
  - Feature narrative + Emotion narrative → keep separate (narrative progression)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import NamedTuple

from backend.agents.timeline.pipeline.analyzer import EnrichedSegment

logger = logging.getLogger(__name__)

MERGE_WEIGHTS = {
    "semantic": 0.30,
    "same_space": 0.25,
    "narrative_role": 0.20,
    "visual_continuity": 0.15,
    "importance": 0.10,
}
MERGE_THRESHOLD = 0.62
# Cap on the merged group's source footage span (seconds). One narration
# sentence covers a merged group; beyond this the voice runs out and the viewer
# watches a long silent walkthrough ("dead air"), which reads as A/V desync.
# Two ~8s angles of one bathroom have to fit, or the tour describes the same
# toilet and tub twice and the buyer thinks the flat has an extra bathroom.
MAX_MERGED_SPAN = 16.0
# Same room, one thin leftover angle (kitchen window after the fridge shot).
# Combined footage may exceed MAX_MERGED_SPAN; a unique appliance close-up
# (dishwasher) must stay its own beat.
THIN_ABSORB_SPAN = 8.0
THIN_ABSORB_TOTAL = 22.0
_UNIQUE_APPLIANCE = (
    "洗碗", "dishwasher", "洗衣", "washer", "dryer", "烤箱", "oven", "洗烘",
)
_THIN_ATMOSPHERE = (
    "窗", "橱柜", "天际", "城市", "window", "cabinet", "skyline", "counter",
)
# A shot Vision could not place has no room to be about. Left standing alone it
# becomes an advertising filler beat ("窗外是开阔的城市天际线") with no room and no
# furniture, so a short one is folded into the neighbour it walked out of.
UNKNOWN_ROOMS = {"", "unknown", "other", "mixed private area", "n/a"}
UNKNOWN_ABSORB_SPAN = 7.0

RELATED_ROOMS: dict[str, set[str]] = {
    "kitchen": {"kitchen", "dining"},
    "dining": {"kitchen", "dining"},
    "bedroom": {"bedroom"},
    "bathroom": {"bathroom"},
    "hallway": {"hallway", "entry", "entryway"},
    "living": {"living", "studio", "lounge"},
    "studio": {"living", "studio", "lounge"},
    "closet": {"closet", "storage"},
}

FEATURE_FUNCTIONS = {"showcase_primary", "feature_highlight", "highlight_amenity"}
EMOTION_FUNCTIONS = {"emotional_resonance", "intimate_reveal", "narrative_climax"}


class MergeCandidate(NamedTuple):
    seg_a: EnrichedSegment
    seg_b: EnrichedSegment
    score: float
    reason: str


@dataclass
class MergeGroup:
    """A group of segments to be collapsed into one timeline entry."""
    segments: list[EnrichedSegment]
    merge_score: float = 0.0
    reason: str = "KEEP"


class SegmentOptimizer:
    """Score and decide which consecutive segment pairs should be merged."""

    def optimize(self, segments: list[EnrichedSegment]) -> list[MergeGroup]:
        groups: list[MergeGroup] = []
        i = 0
        while i < len(segments):
            seg = segments[i]
            if i + 1 < len(segments):
                nxt = segments[i + 1]
                score, reason = self._merge_score(seg, nxt)
                pair_span = float(nxt.video_end) - float(seg.video_start)
                span_cap = self._span_cap(seg, nxt)
                if (
                    self._thin_same_room(seg, nxt)
                    and not self._bedroom_instance_boundary(
                        seg, nxt, seg.room_type.lower().strip(), nxt.room_type.lower().strip()
                    )
                    and not self._mixed_service_boundary(
                        seg, nxt, seg.room_type.lower().strip(), nxt.room_type.lower().strip()
                    )
                    and pair_span <= THIN_ABSORB_TOTAL
                ):
                    score, reason = 0.90, "thin_same_room"
                    span_cap = THIN_ABSORB_TOTAL
                if pair_span > span_cap:
                    score, reason = 0.0, f"span_cap({pair_span:.1f}s>{span_cap:.0f}s)"
                if score >= MERGE_THRESHOLD:
                    logger.info(
                        "Merging %s+%s (score=%.2f reason=%s)",
                        seg.segment_id, nxt.segment_id, score, reason,
                    )
                    merged_group = MergeGroup(segments=[seg, nxt], merge_score=score, reason=reason)
                    # Check if we can absorb a third consecutive if it also merges
                    if i + 2 < len(segments):
                        third = segments[i + 2]
                        s3, r3 = self._merge_score(nxt, third)
                        triple_span = float(third.video_end) - float(seg.video_start)
                        if (
                            s3 >= MERGE_THRESHOLD
                            and third.role != "HERO"
                            and not self._private_room_group_full(merged_group)
                            and triple_span <= self._span_cap(seg, third)
                        ):
                            merged_group.segments.append(third)
                            merged_group.reason += f"+{r3}"
                            i += 1  # extra skip
                    groups.append(merged_group)
                    i += 2
                    continue
            groups.append(MergeGroup(segments=[seg], reason="KEEP"))
            i += 1
        return groups

    def _merge_score(self, a: EnrichedSegment, b: EnrichedSegment) -> tuple[float, str]:
        # VETO: hero segments keep their own window — except when the hero shot
        # is another angle of the room we are already in. Three consecutive
        # kitchen beats read as "we ran out of footage", and the short ones get
        # slowed down to cover a sentence each.
        if a.role == "HERO" or b.role == "HERO":
            room_a_l = a.room_type.lower().strip()
            room_b_l = b.room_type.lower().strip()
            absorbable = (
                room_a_l == room_b_l
                or self._absorbable_unknown(a, room_a_l)
                or self._absorbable_unknown(b, room_b_l)
            )
            if not absorbable:
                return 0.0, "hero_veto"

        # VETO: feature→emotion narrative progression should stay separate
        if self._is_feature(a) and self._is_emotion(b):
            return 0.0, "feature_emotion_progression_veto"

        room_a = a.room_type.lower().strip()
        room_b = b.room_type.lower().strip()

        if self._bedroom_instance_boundary(a, b, room_a, room_b):
            return 0.0, "bedroom_instance_boundary"

        if self._mixed_service_boundary(a, b, room_a, room_b):
            return 0.0, "service_room_boundary"

        unplaced = self._absorbable_unknown(a, room_a) or self._absorbable_unknown(b, room_b)

        # semantic_similarity
        related_a = next((v for k, v in RELATED_ROOMS.items() if k in room_a), {room_a})
        related_b = next((v for k, v in RELATED_ROOMS.items() if k in room_b), {room_b})
        sem = 1.0 if room_a == room_b else (0.5 if related_a & related_b else 0.0)

        # same_space
        same = 1.0 if room_a == room_b else 0.0

        if unplaced and sem < 1.0:
            # Give the orphan shot to its neighbour rather than let it narrate
            # a view with no room attached.
            sem, same = 1.0, 0.6

        # narrative_role compatibility
        role_score = self._role_compat(a.role, b.role)

        # visual_continuity — always 1.0 since we only check consecutive pairs
        continuity = 1.0

        # importance_factor — lower importance → higher merge comfort
        max_imp = max(a.importance, b.importance)
        importance_factor = 1.0 - max_imp  # range: 0..1

        score = (
            sem * MERGE_WEIGHTS["semantic"]
            + same * MERGE_WEIGHTS["same_space"]
            + role_score * MERGE_WEIGHTS["narrative_role"]
            + continuity * MERGE_WEIGHTS["visual_continuity"]
            + importance_factor * MERGE_WEIGHTS["importance"]
        )

        reason = f"room={room_a}≈{room_b} sem={sem:.1f} role={role_score:.1f}"
        return round(score, 3), reason

    def _span_cap(self, a: EnrichedSegment, b: EnrichedSegment) -> float:
        """Footage one narration sentence may cover.

        An unplaced shot needs no words of its own, so it does not count against
        the budget — otherwise the orphan sits between two full rooms, too long
        to absorb either way, and narrates the skyline on its own.
        """
        cap = MAX_MERGED_SPAN
        for seg in (a, b):
            if self._absorbable_unknown(seg, seg.room_type.lower().strip()):
                cap += float(seg.video_end) - float(seg.video_start)
        return cap

    def _absorbable_unknown(self, seg: EnrichedSegment, room: str) -> bool:
        if room not in UNKNOWN_ROOMS:
            return False
        span = float(seg.video_end) - float(seg.video_start)
        return 0 < span <= UNKNOWN_ABSORB_SPAN

    def _thin_same_room(self, a: EnrichedSegment, b: EnrichedSegment) -> bool:
        if a.room_type.lower().strip() != b.room_type.lower().strip():
            return False
        span_a = float(a.video_end) - float(a.video_start)
        span_b = float(b.video_end) - float(b.video_start)
        if min(span_a, span_b) > THIN_ABSORB_SPAN:
            return False
        short = a if span_a <= span_b else b
        blob = " ".join(
            list(short.focus_elements or [])
            + [short.narration_text or "", short.semantic_meaning or "", short.tts_text or ""]
        ).lower()
        if any(token in blob for token in _UNIQUE_APPLIANCE):
            return False
        return any(token in blob for token in _THIN_ATMOSPHERE)

    def _bedroom_instance_boundary(
        self,
        a: EnrichedSegment,
        b: EnrichedSegment,
        room_a: str,
        room_b: str,
    ) -> bool:
        """Avoid narrating several distinct bedrooms as one generic bedroom.

        Vision often labels consecutive private rooms simply as "Bedroom".
        When the visible evidence shifts from view-only to bed/workspace/closet,
        one merged sentence can no longer let the buyer tell which room is which.
        """
        if "bedroom" not in room_a or "bedroom" not in room_b:
            return False
        sig_a = self._bedroom_signature(a)
        sig_b = self._bedroom_signature(b)
        if not sig_a or not sig_b or sig_a == sig_b:
            return False
        if sig_a == {"view"} and "bed" in sig_b:
            return True
        if sig_b == {"view"} and "bed" in sig_a:
            return True
        # A door/entrance reset followed by a new furniture signature is usually
        # a new private-room beat, even if Vision kept the same room_type label.
        stage_b = (getattr(b, "room_stage", "") or "").lower()
        return stage_b in {"entrance", "approaching"} and bool(sig_a ^ sig_b)

    def _bedroom_signature(self, seg: EnrichedSegment) -> set[str]:
        blob = " ".join(
            list(seg.focus_elements or [])
            + [seg.narration_text or "", seg.semantic_meaning or "", seg.tts_text or ""]
        ).lower()
        sig: set[str] = set()
        if any(t in blob for t in ("bed", "床", "bedding", "duvet")):
            sig.add("bed")
        if any(t in blob for t in ("desk", "laptop", "workspace", "书桌", "办公")):
            sig.add("workspace")
        if any(t in blob for t in ("wardrobe", "closet", "衣柜", "收纳")):
            sig.add("storage")
        if any(t in blob for t in ("sea view", "harbor", "window", "窗", "海景", "景观")):
            sig.add("view")
        return sig

    def _mixed_service_boundary(
        self,
        a: EnrichedSegment,
        b: EnrichedSegment,
        room_a: str,
        room_b: str,
    ) -> bool:
        """Keep kitchen/bath/laundry service beats from becoming one fuzzy line."""
        service = ("kitchen", "bathroom", "laundry")
        if room_a == room_b:
            return False
        return any(t in room_a for t in service) and any(t in room_b for t in service)

    def _role_compat(self, role_a: str, role_b: str) -> float:
        if role_a == "HERO" or role_b == "HERO":
            return 1.0 if role_a == role_b else 0.5
        if role_a == role_b:
            return 1.0
        if {role_a, role_b} == {"SUPPORT", "TRANSITION"}:
            return 0.5
        return 0.0

    def _is_feature(self, seg: EnrichedSegment) -> bool:
        fn = seg.narrative_function.lower()
        return any(f in fn for f in FEATURE_FUNCTIONS) or seg.arc_stage == "explore"

    def _is_emotion(self, seg: EnrichedSegment) -> bool:
        fn = seg.narrative_function.lower()
        return any(f in fn for f in EMOTION_FUNCTIONS) or (
            seg.arc_stage == "highlight" and seg.emotion in ("warmth", "intimate", "peaceful")
        )

    def _private_room_group_full(self, group: MergeGroup) -> bool:
        if len(group.segments) < 2:
            return False
        room = (group.segments[0].room_type or "").lower()
        return any(token in room for token in ("bedroom", "bathroom", "laundry"))
