"""Audio Strategy — sound-layer design (not music generation)."""

from __future__ import annotations

from backend.schemas.editing_schema import AudioStrategy, DirectorDecision

PHASE_MOOD: dict[str, str] = {
    "opening_hook": "ambient",
    "emotional_center": "warm",
    "signature_close": "warm",
}


class AudioStrategyPlanner:
    def plan(self, tl_seg: dict, decision: DirectorDecision) -> AudioStrategy:
        story_phase = tl_seg.get("visual_plan", {}).get("story_phase", "")
        mood = PHASE_MOOD.get(story_phase, "neutral")
        if decision.visual_goal:
            mood = decision.visual_goal[:40]
        # Music track not yet available — volume stays 0, design intent preserved
        return AudioStrategy(
            background_music=False,
            music_volume=0.0,
            voice_ducking=True,
            transition_fade=True,
            mood=mood,
        )
