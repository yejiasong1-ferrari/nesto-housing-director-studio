"""Module 5: Knowledge Fusion Engine.

The most important module in the entire Vision Agent.

This is NOT a simple merge. This is REASONING.

When multiple keyframes of the same room produce different
LLM analyses, the Fusion Engine reconciles them into a single
coherent knowledge representation.

For example:
- Image 1 → Kitchen (Modern, Excellent lighting)
- Image 2 → Kitchen (Modern, Good lighting)
- Image 3 → Dining Area (Open, Good lighting)

Fusion → Open Kitchen (Modern, Good lighting, Kitchen Island + Dining Area)

It also produces the Candidate Attention Map by identifying
which visual elements are naturally prominent across all segments.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.schemas.vision_schema import (
    AttentionCandidate,
    CameraKnowledge,
    RoomKnowledge,
    VKBSegment,
)

logger = logging.getLogger(__name__)


class KnowledgeFusionEngine:
    """Fuses per-frame LLM analyses into unified segment knowledge.

    Reconciles conflicting observations, merges selling points,
    and produces candidate attention scores.
    """

    def __init__(self) -> None:
        pass

    def fuse_room_type(self, analyses: list[RoomKnowledge]) -> str:
        """Fuse room type from multiple frame analyses.

        Takes the most confident room type. If types differ,
        uses the one with highest confidence or creates a
        composite description (e.g., "Open Kitchen" for
        Kitchen + Dining Area).
        """
        if not analyses:
            return "Unknown"

        # Count occurrences of each room type
        type_counts: dict[str, int] = {}
        type_confidences: dict[str, float] = {}

        for a in analyses:
            rt = a.room_type
            type_counts[rt] = type_counts.get(rt, 0) + 1
            # Track max confidence for each type
            if rt not in type_confidences or a.confidence > type_confidences[rt]:
                type_confidences[rt] = a.confidence

        # If all agree, use that type
        if len(type_counts) == 1:
            return list(type_counts.keys())[0]

        # If we have a Kitchen + Dining Area → "Open Kitchen"
        types = set(type_counts.keys())
        if "Kitchen" in types and "Dining Area" in types:
            return "Open Kitchen"
        if "Living Room" in types and "Dining Area" in types:
            return "Living/Dining Room"

        # Otherwise, pick the most common type
        return max(type_counts, key=lambda t: type_counts[t])

    def fuse_style(self, analyses: list[RoomKnowledge]) -> str:
        """Fuse decoration style from multiple analyses."""
        if not analyses:
            return ""

        # Most common style
        styles = [a.style for a in analyses if a.style]
        if not styles:
            return ""

        from collections import Counter
        counter = Counter(styles)
        return counter.most_common(1)[0][0]

    def fuse_lighting(self, analyses: list[RoomKnowledge]) -> str:
        """Fuse lighting quality.

        Takes the most common, or the best if mixed.
        In real estate, we conservatively take the most common
        rather than exaggerating.
        """
        if not analyses:
            return ""

        lightings = [a.lighting for a in analyses if a.lighting]
        if not lightings:
            return ""

        from collections import Counter
        counter = Counter(lightings)
        return counter.most_common(1)[0][0]

    def fuse_selling_points(self, analyses: list[RoomKnowledge]) -> list[str]:
        """Merge selling points from multiple analyses.

        Deduplicates and keeps all unique selling points.
        """
        all_points = []
        for a in analyses:
            all_points.extend(a.selling_points)

        # Deduplicate (case-insensitive)
        seen: set[str] = set()
        unique = []
        for point in all_points:
            lower = point.lower()
            if lower not in seen:
                seen.add(lower)
                unique.append(point)

        return unique

    def fuse_camera(self, analyses: list[RoomKnowledge]) -> CameraKnowledge:
        """Fuse camera motion descriptions."""
        if not analyses:
            return CameraKnowledge()

        motions = [a.camera.motion for a in analyses if a.camera.motion]
        speeds = [a.camera.speed for a in analyses if a.camera.speed]

        from collections import Counter

        motion = Counter(motions).most_common(1)[0][0] if motions else ""
        speed = Counter(speeds).most_common(1)[0][0] if speeds else ""

        return CameraKnowledge(motion=motion, speed=speed)

    def fuse_segment(
        self,
        segment_id: str,
        analyses: list[RoomKnowledge],
    ) -> RoomKnowledge:
        """Fuse multiple frame analyses into a single RoomKnowledge.

        Args:
            segment_id: Segment identifier.
            analyses: List of per-frame RoomKnowledge analyses.

        Returns:
            Unified RoomKnowledge for this segment.
        """
        if not analyses:
            return RoomKnowledge(room_type="Unknown", confidence=0.0)

        # Preserve any pre-attached space inventory from upstream analyzers.
        fused_spaces = []
        for a in analyses:
            if a.spaces:
                fused_spaces.extend(a.spaces)

        fused = RoomKnowledge(
            room_type=self.fuse_room_type(analyses),
            confidence=max(a.confidence for a in analyses),
            style=self.fuse_style(analyses),
            layout=analyses[0].layout if analyses else "",
            lighting=self.fuse_lighting(analyses),
            selling_points=self.fuse_selling_points(analyses),
            furniture=[item for a in analyses for item in a.furniture],
            appliances=[item for a in analyses for item in a.appliances],
            camera=self.fuse_camera(analyses),
            notes="",
            spaces=list(fused_spaces),
        )

        # Deduplicate furniture and appliances
        fused.furniture = list(dict.fromkeys(fused.furniture))
        fused.appliances = list(dict.fromkeys(fused.appliances))

        logger.info(
            f"Fused segment {segment_id}: {fused.room_type} "
            f"(style: {fused.style}, lighting: {fused.lighting}, "
            f"{len(fused.selling_points)} selling points)"
        )
        return fused

    def generate_attention_candidates(
        self, segments: list[VKBSegment]
    ) -> list[AttentionCandidate]:
        """Generate candidate attention map from selling points.

        Vision Agent identifies what is visually prominent.
        Planner decides what should be emphasized editorially.
        Editing Strategy decides how to highlight it.

        These three responsibilities are fully decoupled.
        """
        candidates = []

        for seg in segments:
            for point in seg.knowledge.selling_points:
                # Score based on:
                # - Room confidence (higher confidence = more reliable observation)
                # - Lighting quality (well-lit features are more visible)
                # - Selling point specificity (named brands/specific features score higher)

                base_score = seg.confidence

                # Lighting boost
                lighting_map = {"Excellent": 0.1, "Good": 0.05, "Fair": 0.0, "Poor": -0.05}
                base_score += lighting_map.get(seg.knowledge.lighting, 0.0)

                # Specificity boost: named items (brands, specific features)
                specificity_keywords = [
                    "bosch", "sub-zero", "wolf", "miele", "gaggenau",
                    "island", "vaulted", "ceiling", "bay window",
                    "floor-to-ceiling", "granite", "marble", "quartz",
                    "hardwood", "fireplace", "walk-in",
                ]
                point_lower = point.lower()
                for kw in specificity_keywords:
                    if kw in point_lower:
                        base_score += 0.05

                # Cap at 1.0
                score = min(base_score, 1.0)

                candidates.append(
                    AttentionCandidate(
                        target=point,
                        segment_id=seg.segment_id,
                        score=round(score, 2),
                        reason=f"Prominent feature in {seg.knowledge.room_type}",
                    )
                )

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)

        logger.info(f"Generated {len(candidates)} attention candidates")
        return candidates

    def fuse_all(
        self,
        raw_segments: list[Any],
        analyses_per_segment: list[list[RoomKnowledge]],
    ) -> tuple[list[VKBSegment], list[AttentionCandidate]]:
        """Fuse all segment analyses into complete VKB.

        Args:
            raw_segments: List of RawSegment objects with timestamps and keyframes.
            analyses_per_segment: Per-frame analyses for each segment.

        Returns:
            Tuple of (list of VKBSegments, attention candidates).
        """
        vkb_segments = []

        for i, raw_seg in enumerate(raw_segments):
            analyses = analyses_per_segment[i] if i < len(analyses_per_segment) else []
            seg_id = getattr(raw_seg, '__dict__', {}).get('segment_id', f'seg_{i + 1:02d}')

            fused_knowledge = self.fuse_segment(seg_id, analyses)

            vkb_seg = VKBSegment(
                segment_id=seg_id,
                confidence=fused_knowledge.confidence,
                raw=raw_seg,
                knowledge=fused_knowledge,
            )
            vkb_segments.append(vkb_seg)

        attention_candidates = self.generate_attention_candidates(vkb_segments)

        logger.info(
            f"Fusion complete: {len(vkb_segments)} segments, "
            f"{len(attention_candidates)} attention candidates"
        )
        return vkb_segments, attention_candidates
