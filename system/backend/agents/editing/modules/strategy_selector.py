"""Capability 1: Strategy Selector.

Rule engine selects base visual strategy per segment.
LLM can augment for HERO segments (optional, falls back to rules).
"""

from __future__ import annotations

from backend.schemas.editing_schema import VisualStrategy

IMPORTANCE_SLOW_MOTION = 0.75
IMPORTANCE_ZOOM = 0.80
HERO_ZOOM_SCALE = 1.12
SUPPORT_ZOOM_SCALE = 1.06


class StrategySelector:
    """Select primary visual strategy from timeline segment metadata."""

    def select(self, tl_seg: dict, dur_strategy: str = "") -> list[VisualStrategy]:
        role = tl_seg.get("role", "SUPPORT")
        importance = float(tl_seg.get("importance", 0.5))
        arc_stage = tl_seg.get("arc_stage", "explore")
        story_phase = tl_seg.get("visual_plan", {}).get("story_phase", "")
        dur_dec = tl_seg.get("duration_decision", {})
        tl_strategy = dur_dec.get("strategy", dur_strategy)
        extension_factor = float(dur_dec.get("extension_factor", 1.0))
        editing_window = float(dur_dec.get("editing_window", 0))
        video_duration = float(tl_seg.get("source", {}).get("video_duration", editing_window))

        strategies: list[VisualStrategy] = []

        # Primary effect from Timeline duration decision — slow-mo only for
        # in-space A/V fill (freeze pause is not used for narration overrun).
        if tl_strategy in ("slow_motion", "freeze_frame", "zoom_extend") and (
            extension_factor < 1.0 or editing_window > video_duration + 0.05
        ):
            speed = extension_factor if extension_factor < 1.0 else (
                video_duration / editing_window if editing_window > 0 else 1.0
            )
            strategies.append(VisualStrategy(
                type="slow_motion",
                parameters={
                    "speed": round(speed, 3),
                    "editing_window": editing_window,
                    "allow_freeze": False,
                },
                reason=f"Extend {role} moment via continuous slow-motion ({speed:.2f}x)",
            ))

        # Secondary emphasis for HERO/important segments
        if role == "HERO" and importance >= IMPORTANCE_ZOOM:
            focus = tl_seg.get("visual_plan", {}).get("focus_elements", [])
            target = focus[0] if focus else tl_seg.get("room_type", "")
            strategies.append(VisualStrategy(
                type="zoom",
                parameters={"scale": HERO_ZOOM_SCALE, "target": target},
                reason=f"Hero segment zoom on '{target}'",
            ))
        elif importance >= IMPORTANCE_ZOOM and arc_stage == "highlight":
            strategies.append(VisualStrategy(
                type="zoom",
                parameters={"scale": SUPPORT_ZOOM_SCALE},
                reason="Subtle zoom for highlight arc",
            ))

        if not strategies:
            strategies.append(VisualStrategy(
                type="clean_cut",
                parameters={},
                reason="Standard cut — no adjustment needed",
            ))

        return strategies
