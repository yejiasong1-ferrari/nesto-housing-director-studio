"""Capability 5: Editing Transition Planner.

Extracts and refines transition directives from Timeline output.
"""

from __future__ import annotations

# Minimum rendering duration for each transition type
TRANSITION_DURATIONS: dict[str, float] = {
    "cut": 0.0,
    "quick_cut": 0.0,
    "soft_pan": 0.5,
    "camera_pan": 0.7,
    "dissolve": 0.6,
    "fade": 0.8,
}


class EditingTransitionPlanner:
    """Map timeline transition to editing-layer transition parameters."""

    def plan(self, tl_seg: dict) -> tuple[str, float]:
        trans = tl_seg.get("transition", {})
        t_type = trans.get("type", "cut")
        t_dur = float(trans.get("duration", 0))
        if t_dur == 0:
            t_dur = TRANSITION_DURATIONS.get(t_type, 0.0)
        return t_type, t_dur
