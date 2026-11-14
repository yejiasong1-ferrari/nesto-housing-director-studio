"""Module 5: Transition Planner.

Decides the transition between each consecutive pair of timeline segments.

Rules:
  same room       → cut (fast, invisible edit)
  TRANSITION role → quick_cut (minimal screen time, snappy)
  HERO → any      → soft_pan (cinematic entry into the next space)
  any  → HERO     → soft_pan (cinematic arrival at the centrepiece)
  interior → exterior (or reverse) → fade (temporal jump)
  bedroom → bathroom → dissolve (intimate flow)
  default         → cut
"""

from __future__ import annotations

import logging

from backend.agents.timeline.pipeline.segment_optimizer import MergeGroup

logger = logging.getLogger(__name__)

TRANSITION_DURATIONS: dict[str, float] = {
    "cut": 0.0,
    "quick_cut": 0.0,
    "soft_pan": 0.8,
    "camera_pan": 1.0,
    "dissolve": 0.6,
    "fade": 1.0,
}

INTIMATE_ROOMS = {"bathroom", "bedroom", "closet"}
EXTERIOR_ROOMS = {"exterior", "balcony", "garden", "garage", "patio"}


class TransitionPlanner:
    """Plan the transition between consecutive segment groups."""

    def __init__(self, continuous_walkthrough: bool = True) -> None:
        self.continuous_walkthrough = continuous_walkthrough

    def plan_all(self, groups: list[MergeGroup]) -> list[dict]:
        """Return list of transition dicts aligned with groups (last = no next)."""
        transitions: list[dict] = []
        for idx, group in enumerate(groups):
            if idx + 1 < len(groups):
                t_type, reason = self._pick_type(group, groups[idx + 1])
                t_dur = TRANSITION_DURATIONS.get(t_type, 0.3)
                transitions.append({
                    "type": t_type,
                    "duration": t_dur,
                    "reason": reason,
                })
            else:
                # End: cut avoids crossfade that would eat the final frames
                transitions.append({
                    "type": "cut",
                    "duration": 0.0,
                    "reason": "end_of_video",
                })
        return transitions

    def _pick_type(self, current: MergeGroup, nxt: MergeGroup) -> tuple[str, str]:
        # One-shot walkthrough: hard cuts only — dissolves/soft_pans overlap
        # and permanently discard source frames in Rendering.
        if self.continuous_walkthrough:
            cur_role = current.segments[-1].role
            nxt_role = nxt.segments[0].role
            if cur_role == "TRANSITION" or nxt_role == "TRANSITION":
                return "quick_cut", "continuous_walkthrough_transition"
            return "cut", "continuous_walkthrough"

        cur_room = current.segments[-1].room_type.lower()
        nxt_room = nxt.segments[0].room_type.lower()
        cur_role = current.segments[-1].role
        nxt_role = nxt.segments[0].role

        # Exterior boundary
        cur_ext = any(e in cur_room for e in EXTERIOR_ROOMS)
        nxt_ext = any(e in nxt_room for e in EXTERIOR_ROOMS)
        if cur_ext != nxt_ext:
            return "fade", "interior_exterior_boundary"

        # Hero transitions get cinematic treatment
        if cur_role == "HERO" or nxt_role == "HERO":
            return "soft_pan", "hero_transition"

        # Same room → invisible cut
        if cur_room == nxt_room:
            return "cut", "same_room"

        # Intimate room adjacent pair
        if cur_room in INTIMATE_ROOMS and nxt_room in INTIMATE_ROOMS:
            return "dissolve", "intimate_flow"

        # Transition role → quick
        if cur_role == "TRANSITION" or nxt_role == "TRANSITION":
            return "quick_cut", "transition_segment"

        return "cut", "default"
