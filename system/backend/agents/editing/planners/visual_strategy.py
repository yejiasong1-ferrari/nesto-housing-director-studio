"""Visual Strategy Planner — maps LLM director intent → VisualOperation list."""

from __future__ import annotations

from backend.schemas.editing_schema import (
    DirectorDecision,
    VisualOperation,
    VisualStrategyBlock,
)

STYLE_TO_OP: dict[str, str] = {
    "slow_push": "slow_zoom",
    "slow_zoom": "slow_zoom",
    "ken_burns": "ken_burns",
    "zoom": "zoom",
    "wide_shot": "clean_cut",
    "freeze_hold": "freeze_frame",
    "freeze_frame": "freeze_frame",
    "slow_motion": "slow_motion",
}


class VisualStrategyPlanner:
    """Convert director recommended_style + timeline duration strategy into ops."""

    def plan(
        self,
        decision: DirectorDecision,
        tl_seg: dict,
    ) -> VisualStrategyBlock:
        focus = [f.element for f in decision.focus_order if f.element]
        if not focus:
            focus = list(tl_seg.get("visual_plan", {}).get("focus_elements", [])[:2])
            if not focus:
                focus = [tl_seg.get("room_type", "space")]

        dur_dec = tl_seg.get("duration_decision", {})
        tl_strategy = dur_dec.get("strategy", "")
        extension_factor = float(dur_dec.get("extension_factor", 1.0))
        editing_window = float(dur_dec.get("editing_window", 0))
        video_duration = float(tl_seg.get("source", {}).get("video_duration", editing_window))
        role = tl_seg.get("role", "SUPPORT")
        importance = float(tl_seg.get("importance", 0.5))

        ops: list[VisualOperation] = []

        # Duration-driven ops take priority (Timeline already decided time fill).
        # In-space audio overrun → continuous slow-motion (never freeze pause).
        if tl_strategy in ("slow_motion", "freeze_frame", "zoom_extend") and (
            extension_factor < 1.0 or editing_window > video_duration + 0.05
        ):
            speed = extension_factor if extension_factor < 1.0 else (
                video_duration / editing_window if editing_window > 0 else 1.0
            )
            ops.append(VisualOperation(
                type="slow_motion",
                target=focus[0],
                strength=round(max(0.0, 1.0 - speed), 3),
                parameters={
                    "speed": round(speed, 3),
                    "editing_window": editing_window,
                    "allow_freeze": False,
                },
                reason="Match narration window via continuous slow-motion (no pause)",
            ))

        # Director style → motion ops (if duration didn't already set motion)
        styles = [s.lower().replace("-", "_") for s in decision.recommended_style]
        has_motion = any(o.type in ("slow_motion", "ken_burns", "slow_zoom", "freeze_frame") for o in ops)

        if not has_motion:
            if "slow_push" in styles or "slow_zoom" in styles or "ken_burns" in styles:
                strength = 0.7 if role == "HERO" else 0.5
                zoom_end = 1.0 + 0.12 * strength
                ops.append(VisualOperation(
                    type="slow_zoom",
                    target=focus[0],
                    strength=strength,
                    parameters={
                        "zoom_start": 1.0,
                        "zoom_end": round(zoom_end, 3),
                        "editing_window": editing_window or video_duration,
                    },
                    reason=decision.visual_goal or "Director slow push",
                ))
            elif "zoom" in styles or (role == "HERO" and importance >= 0.8):
                scale = 1.12 if role == "HERO" else 1.06
                ops.append(VisualOperation(
                    type="zoom",
                    target=focus[0],
                    strength=0.6 if role == "HERO" else 0.4,
                    parameters={"scale": scale, "target": focus[0]},
                    reason=decision.visual_goal or "Emphasis zoom",
                ))

        if not ops:
            ops.append(VisualOperation(
                type="clean_cut",
                target=focus[0] if focus else "",
                strength=0.0,
                parameters={},
                reason="Wide presentation — no motion needed",
            ))

        return VisualStrategyBlock(focus=focus, operations=ops)
