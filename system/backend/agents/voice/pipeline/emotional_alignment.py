"""Capability 5: Emotional Alignment.

Aligns voice delivery emotion/energy with scene emotion and visual context.
"""

from __future__ import annotations

from typing import Any

from backend.schemas.voice_schema import VoiceDelivery

EMOTION_MAP: dict[str, dict[str, str | float]] = {
    "curiosity": {"emotion": "curious", "energy": "medium", "speed_adj": 0.02},
    "warm": {"emotion": "warm", "energy": "medium", "speed_adj": -0.03},
    "warmth": {"emotion": "warm", "energy": "medium", "speed_adj": -0.03},
    "premium": {"emotion": "confident", "energy": "high", "speed_adj": -0.05},
    "peaceful": {"emotion": "peaceful", "energy": "low", "speed_adj": -0.08},
    "neutral": {"emotion": "neutral", "energy": "medium", "speed_adj": 0.0},
    "excitement": {"emotion": "enthusiastic", "energy": "high", "speed_adj": 0.03},
    "intimate": {"emotion": "intimate", "energy": "low", "speed_adj": -0.06},
}


class EmotionalAlignment:
    """Refine delivery to match scene emotion from Script Agent."""

    def align(self, segment: dict[str, Any], delivery: VoiceDelivery) -> VoiceDelivery:
        scene_emotion = str(segment.get("emotion", "neutral")).lower()
        mapping = EMOTION_MAP.get(scene_emotion, EMOTION_MAP["neutral"])

        speed_adj = float(mapping.get("speed_adj", 0.0))
        new_speed = max(0.7, min(1.1, delivery.speed + speed_adj))

        pitch = delivery.pitch
        energy = str(mapping.get("energy", delivery.energy))
        if energy == "low":
            pitch = "low"
        elif energy == "high":
            pitch = "medium"

        pause_after = delivery.pause_after
        if scene_emotion in ("peaceful", "intimate", "warm", "warmth"):
            pause_after += 0.2

        return VoiceDelivery(
            emotion=str(mapping.get("emotion", delivery.emotion)),
            speed=round(new_speed, 2),
            pitch=pitch,
            pause_before=delivery.pause_before,
            pause_after=round(pause_after, 2),
            energy=energy,
        )
