"""Editing constraint validator — sanitize LLM/director output for walkthroughs."""

from __future__ import annotations

import logging

from backend.schemas.editing_schema import (
    EditingSegmentPlan,
    VisualOperation,
)

logger = logging.getLogger(__name__)

ALLOWED_OPS = {
    "clean_cut",
    "slow_zoom",
    "zoom",
    "ken_burns",
    "slow_motion",
    "freeze_frame",
    "crop",
}

FORBIDDEN_OPS = {
    "dramatic_camera_rotation",
    "camera_rotation",
    "whip_pan",
    "3d_rotate",
    "spin",
    "orbit",
    "dolly_physical",
}

ALLOWED_TRANSITIONS = {
    "cut", "quick_cut", "soft_pan", "smooth_pan",
    "camera_pan", "dissolve", "fade",
}

MAX_TRANSITION_DURATION = 2.0
MAX_ZOOM_END = 1.20
MAX_STATIC_SCALE = 1.18
MIN_SLOW_SPEED = 0.55   # never slower than this (avoids extreme stutter)
MAX_SLOW_SPEED = 0.95


class EditingConstraintValidator:
    """Reject illegal ops; clamp parameters for walkthrough + no camera control."""

    def validate_segment(self, plan: EditingSegmentPlan) -> EditingSegmentPlan:
        # Never allow time mutation — re-assert from existing fields only
        ops = [self._sanitize_op(op) for op in plan.visual_strategy.operations]
        if not ops:
            ops = [VisualOperation(type="clean_cut", reason="validator_default")]
        plan.visual_strategy.operations = ops

        if plan.transition.type not in ALLOWED_TRANSITIONS:
            logger.info(
                "Validator: illegal transition %s → soft_pan", plan.transition.type
            )
            plan.transition.type = "soft_pan"
            plan.transition.reason = "validator_replaced_illegal_transition"

        if plan.transition.duration > MAX_TRANSITION_DURATION:
            plan.transition.duration = MAX_TRANSITION_DURATION

        if plan.transition.duration < 0:
            plan.transition.duration = 0.0

        # Clamp audio volume
        plan.audio.music_volume = max(0.0, min(0.3, plan.audio.music_volume))

        plan.sync_legacy_fields()
        return plan

    def _sanitize_op(self, op: VisualOperation) -> VisualOperation:
        raw = (op.type or "clean_cut").lower().replace("-", "_")

        if raw in FORBIDDEN_OPS or raw not in ALLOWED_OPS:
            logger.info("Validator: illegal op %s → slow_zoom", op.type)
            return VisualOperation(
                type="slow_zoom",
                target=op.target,
                strength=min(op.strength or 0.5, 0.7),
                parameters={
                    "zoom_start": 1.0,
                    "zoom_end": 1.08,
                    "editing_window": op.parameters.get("editing_window", 0),
                },
                reason=f"validator_replaced:{op.type}",
            )

        params = dict(op.parameters or {})

        if raw == "slow_motion":
            speed = float(params.get("speed", 0.8))
            speed = max(MIN_SLOW_SPEED, min(MAX_SLOW_SPEED, speed))
            params["speed"] = round(speed, 3)

        if raw in ("slow_zoom", "ken_burns"):
            z_end = float(params.get("zoom_end", 1.08))
            params["zoom_end"] = min(z_end, MAX_ZOOM_END)
            params["zoom_start"] = float(params.get("zoom_start", 1.0))

        if raw == "zoom":
            scale = float(params.get("scale", 1.10))
            params["scale"] = min(scale, MAX_STATIC_SCALE)

        return VisualOperation(
            type=raw,
            target=op.target,
            strength=max(0.0, min(1.0, float(op.strength or 0.5))),
            parameters=params,
            reason=op.reason,
        )
