"""Pacing Strategy — motion feel within a fixed timeline window.

Does NOT change segment duration. Timeline owns time; Editing owns motion.
"""

from __future__ import annotations

from backend.schemas.editing_schema import DirectorDecision, MotionProfile

ROLE_PROFILE: dict[str, MotionProfile] = {
    "HERO": MotionProfile(
        style="cinematic", speed=0.8,
        camera_change_frequency="low", hold_time="long",
    ),
    "SUPPORT": MotionProfile(
        style="normal", speed=1.0,
        camera_change_frequency="normal", hold_time="normal",
    ),
    "TRANSITION": MotionProfile(
        style="brisk", speed=1.1,
        camera_change_frequency="high", hold_time="short",
    ),
    "CLOSE": MotionProfile(
        style="fade_out", speed=0.85,
        camera_change_frequency="low", hold_time="long",
    ),
}

HINT_SPEED: dict[str, float] = {
    "slow": 0.8,
    "medium": 1.0,
    "fast": 1.15,
}


class PacingStrategyPlanner:
    def plan(self, tl_seg: dict, decision: DirectorDecision) -> MotionProfile:
        role = tl_seg.get("role", "SUPPORT")
        arc = tl_seg.get("arc_stage", "explore")

        if arc == "close":
            base = ROLE_PROFILE["CLOSE"].model_copy()
        else:
            base = ROLE_PROFILE.get(role, ROLE_PROFILE["SUPPORT"]).model_copy()

        hint = (decision.pacing_hint or "").lower()
        if hint in HINT_SPEED:
            base.speed = HINT_SPEED[hint]
            if hint == "slow":
                base.camera_change_frequency = "low"
                base.hold_time = "long"
                base.style = "cinematic"
            elif hint == "fast":
                base.camera_change_frequency = "high"
                base.hold_time = "short"
                base.style = "brisk"

        return base
