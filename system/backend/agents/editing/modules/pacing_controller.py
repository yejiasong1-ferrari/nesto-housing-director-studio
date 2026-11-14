"""Capability 3: Cinematic Pacing Controller.

Maps story phase / arc stage to pacing and cut frequency.
"""

from __future__ import annotations

PHASE_PACING: dict[str, tuple[str, str]] = {
    "opening_hook":    ("slow", "low"),
    "discovery":       ("medium", "normal"),
    "living_experience": ("medium", "normal"),
    "emotional_center": ("slow", "low"),
    "core_spaces":     ("medium", "normal"),
    "private_retreat": ("medium", "low"),
    "luxury_detail":   ("slow", "low"),
    "signature_close": ("slow", "low"),
}

ARC_PACING: dict[str, tuple[str, str]] = {
    "hook":      ("slow", "low"),
    "explore":   ("medium", "normal"),
    "highlight": ("slow", "low"),
    "close":     ("slow", "low"),
}


class PacingController:
    """Determine pace and cut frequency for a segment."""

    def decide(self, tl_seg: dict) -> tuple[str, str]:
        story_phase = tl_seg.get("visual_plan", {}).get("story_phase", "")
        arc_stage = tl_seg.get("arc_stage", "explore")
        if story_phase in PHASE_PACING:
            return PHASE_PACING[story_phase]
        return ARC_PACING.get(arc_stage, ("medium", "normal"))
