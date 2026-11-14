"""Capability 2: Speech Rhythm Planning.

Decides per-segment speed and pauses based on narrative arc and role.
"""

from __future__ import annotations

from typing import Any

from backend.schemas.voice_schema import VoiceDelivery

ARC_SPEED: dict[str, float] = {
    "hook": 0.88,
    "explore": 0.95,
    "highlight": 0.92,
    "close": 0.85,
}

ROLE_SPEED_ADJ: dict[str, float] = {
    "HERO": -0.03,
    "SUPPORT": 0.0,
    "TRANSITION": 0.05,
}

ARC_PAUSE_AFTER: dict[str, float] = {
    "hook": 0.6,
    "explore": 0.4,
    "highlight": 0.5,
    "close": 1.0,
}


class RhythmPlanner:
    """Plan speaking rhythm for each narration segment."""

    def plan(
        self,
        segment: dict[str, Any],
        profile_emotion: str = "confident",
    ) -> VoiceDelivery:
        arc = str(segment.get("arc_stage", "explore")).lower()
        role = str(segment.get("role", "SUPPORT")).upper()

        base_speed = ARC_SPEED.get(arc, 0.95)
        base_speed += ROLE_SPEED_ADJ.get(role, 0.0)
        base_speed = max(0.75, min(1.1, base_speed))

        pause_before = 0.5 if arc == "hook" and segment.get("start_time", 0) == 0 else 0.2
        if role == "TRANSITION":
            pause_before = max(pause_before, 0.3)

        pause_after = ARC_PAUSE_AFTER.get(arc, 0.4)
        if role == "HERO":
            pause_after += 0.2

        energy = "low" if arc == "close" else "medium"
        if role == "HERO":
            energy = "high"

        return VoiceDelivery(
            emotion=profile_emotion,
            speed=round(base_speed, 2),
            pitch="medium",
            pause_before=round(pause_before, 2),
            pause_after=round(pause_after, 2),
            energy=energy,
        )
