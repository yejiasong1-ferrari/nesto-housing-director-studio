"""Transition Strategy — how segments connect (duration capped by validator)."""

from __future__ import annotations

from backend.schemas.editing_schema import DirectorDecision, TransitionStrategy

DEFAULT_DURATIONS: dict[str, float] = {
    "cut": 0.0,
    "quick_cut": 0.0,
    "soft_pan": 0.30,
    "smooth_pan": 0.35,
    "camera_pan": 0.30,
    "dissolve": 0.30,
    "fade": 0.35,
}

HINT_MAP: dict[str, str] = {
    "soft_pan": "soft_pan",
    "smooth_pan": "soft_pan",
    "dissolve": "dissolve",
    "fade": "fade",
    "cut": "cut",
    "quick_cut": "quick_cut",
}

MAX_TRANSITION_DURATION = 0.40
# Overlap transitions discard source frames — forbidden for one-shot tours
OVERLAP_TYPES = {"soft_pan", "smooth_pan", "camera_pan", "dissolve", "fade"}


class TransitionStrategyPlanner:
    def __init__(self, continuous_walkthrough: bool = True) -> None:
        self.continuous_walkthrough = continuous_walkthrough

    def plan(
        self,
        tl_seg: dict,
        decision: DirectorDecision,
        prev_room: str = "",
    ) -> TransitionStrategy:
        trans = tl_seg.get("transition", {})
        t_type = str(trans.get("type", "cut"))
        t_dur = float(trans.get("duration", 0) or 0)
        reason = str(trans.get("reason", "from_timeline"))

        if self.continuous_walkthrough:
            # Never upgrade to overlap transitions — keep every walkthrough frame
            if t_type in OVERLAP_TYPES or t_type not in ("cut", "quick_cut"):
                t_type = "cut"
                reason = "continuous_walkthrough"
            return TransitionStrategy(type=t_type, duration=0.0, reason=reason)

        hint = (decision.transition_hint or "").lower().replace("-", "_")
        if hint in HINT_MAP:
            t_type = HINT_MAP[hint]
            reason = decision.reason or "director_hint"

        cur_room = tl_seg.get("room_type", "")
        if prev_room and cur_room and prev_room.lower() == cur_room.lower():
            if t_type in ("cut", "quick_cut"):
                t_type = "soft_pan"
                reason = "maintain spatial continuity"

        if t_dur <= 0:
            t_dur = DEFAULT_DURATIONS.get(t_type, 0.0)

        t_dur = min(t_dur, MAX_TRANSITION_DURATION)
        return TransitionStrategy(type=t_type, duration=t_dur, reason=reason)
