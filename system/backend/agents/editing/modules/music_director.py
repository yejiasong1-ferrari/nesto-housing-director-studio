"""Capability 6: Music / Atmosphere Planner (stub).

Future: select background music mood and volume per segment.
"""

from __future__ import annotations

from backend.schemas.editing_schema import MusicCue

PHASE_MOODS: dict[str, tuple[str, float]] = {
    "opening_hook": ("ambient", 0.3),
    "emotional_center": ("warm", 0.2),
    "signature_close": ("warm", 0.25),
}


class MusicDirector:
    def plan(self, tl_seg: dict) -> MusicCue:
        story_phase = tl_seg.get("visual_plan", {}).get("story_phase", "")
        mood, energy = PHASE_MOODS.get(story_phase, ("neutral", 0.15))
        return MusicCue(mood=mood, energy=energy, volume=0.0)  # volume=0 = no music yet
