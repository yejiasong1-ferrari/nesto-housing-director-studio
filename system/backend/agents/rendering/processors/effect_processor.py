"""Effect Processor — apply visual effects from Editing Strategy.

Within a space, audio overrun is filled by continuous slow-motion
(MultiplySpeed remap once) — not freeze-frame pause. Mild speeds are
preferred; Timeline should FLAG_REWRITE when stretch would be extreme.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Floor for deliberate style slow-mo when no editing_window is set.
# For A/V fill we stretch to the exact window (see allow_freeze=False).
MIN_PLAYBACK_SPEED = 0.45
MAX_ZOOM = 1.15


def crop_or_pad_frame(frame: np.ndarray, height: int, width: int) -> np.ndarray:
    """Center-crop or pad so ``frame`` is exactly ``height × width``.

    ``vfx.Resize`` rounds independently on the RGB clip and its mask, so they
    can land one pixel apart (1920 vs 1921). MoviePy then crashes in
    ``np.dstack([frame, mask])`` on export.
    """
    arr = np.asarray(frame)
    fh, fw = arr.shape[:2]
    if fh == height and fw == width:
        return arr

    if fh < height or fw < width:
        pad_h = max(0, height - fh)
        pad_w = max(0, width - fw)
        top, bottom = pad_h // 2, pad_h - pad_h // 2
        left, right = pad_w // 2, pad_w - pad_w // 2
        if arr.ndim == 2:
            pad_spec = ((top, bottom), (left, right))
        else:
            pad_spec = ((top, bottom), (left, right), (0, 0))
        arr = np.pad(arr, pad_spec, mode="edge")
        fh, fw = arr.shape[:2]

    top = max(0, (fh - height) // 2)
    left = max(0, (fw - width) // 2)
    return arr[top:top + height, left:left + width]


def lock_clip_size(clip, width: int, height: int):
    """Force every frame (and mask) onto a fixed canvas; keep ``clip.size`` honest."""
    w, h = int(width), int(height)

    def _fit(get_frame, t):
        return crop_or_pad_frame(get_frame(t), h, w)

    out = clip.transform(_fit, apply_to="mask").with_duration(clip.duration)
    out.size = (w, h)
    return out


class EffectProcessor:
    """Apply visual effects to a clip based on Editing Strategy directives."""

    def __init__(self, preserve_full_span: bool = True) -> None:
        self.preserve_full_span = preserve_full_span

    def apply(self, clip, strategy_type: str, params: dict):
        op = (strategy_type or "clean_cut").lower().replace("-", "_")
        if op == "slow_motion":
            return self._slow_motion(clip, params)
        if op == "freeze_frame":
            return self._freeze_frame(clip, params)
        if op == "zoom":
            return self._zoom(clip, params)
        if op in ("ken_burns", "slow_zoom"):
            return self._ken_burns(clip, params)
        if op == "crop":
            return self._zoom(clip, {"scale": float(params.get("scale", 1.05))})
        return clip

    def _slow_motion(self, clip, params: dict):
        """Stretch clip smoothly to editing_window.

        Default: remap once to the full window so narration can finish while
        the walkthrough keeps moving (no in-space freeze pause).
        Optional allow_freeze=True restores legacy cap + freeze remainder.
        """
        from moviepy import vfx

        editing_window = float(params.get("editing_window", 0) or 0)
        allow_freeze = bool(params.get("allow_freeze", False))
        min_speed = float(params.get("min_speed", MIN_PLAYBACK_SPEED) or MIN_PLAYBACK_SPEED)
        min_speed = max(0.25, min(0.95, min_speed))

        if editing_window <= 0:
            speed = max(min_speed, min(0.95, float(params.get("speed", 0.85))))
            return clip.with_effects([vfx.MultiplySpeed(factor=speed)])

        if editing_window <= clip.duration + 0.05:
            if self.preserve_full_span:
                return clip
            return clip.with_duration(editing_window)

        if allow_freeze:
            max_stretch = clip.duration / min_speed
            target = min(editing_window, max_stretch)
        else:
            # Keep motion for the whole narration window (user preference).
            target = editing_window

        logger.debug(
            "slow_motion: src=%.2fs → %.2fs (allow_freeze=%s, min_speed=%.2f)",
            clip.duration, target, allow_freeze, min_speed,
        )
        slowed = clip.with_effects([vfx.MultiplySpeed(final_duration=target)])

        if allow_freeze and slowed.duration + 0.05 < editing_window:
            gap = editing_window - slowed.duration
            freeze_at = max(0.0, slowed.duration - 0.04)
            slowed = slowed.with_effects([
                vfx.Freeze(t=freeze_at, freeze_duration=gap)
            ])
        return slowed

    def _freeze_frame(self, clip, params: dict):
        """Legacy hold — prefer slow_motion for A/V fill; kept for explicit ops."""
        from moviepy import vfx

        freeze_at = float(params.get("freeze_at", clip.duration - 0.05))
        editing_window = float(params.get("editing_window", clip.duration))
        freeze_at = min(max(0.0, freeze_at), max(0.0, clip.duration - 0.05))
        hold = max(0.0, editing_window - clip.duration)
        if hold <= 0.01:
            return clip
        logger.debug("freeze_frame: at=%.2f hold=%.2fs", freeze_at, hold)
        return clip.with_effects([vfx.Freeze(t=freeze_at, freeze_duration=hold)])

    def _zoom(self, clip, params: dict):
        from moviepy import vfx

        scale = float(params.get("scale", 1.08))
        strength = params.get("strength")
        if strength is not None and "scale" not in params:
            scale = 1.0 + 0.12 * float(strength)
        scale = min(max(scale, 1.0), MAX_ZOOM)
        w, h = clip.size
        zoomed = clip.with_effects([vfx.Resize(scale)])
        return lock_clip_size(zoomed, w, h)

    def _ken_burns(self, clip, params: dict):
        """Gradual zoom via time-varying Resize (MoviePy native)."""
        from moviepy import vfx

        zoom_start = float(params.get("zoom_start", 1.0))
        zoom_end = float(params.get("zoom_end", 1.08))
        strength = params.get("strength")
        if strength is not None and "zoom_end" not in params:
            zoom_end = 1.0 + 0.10 * float(strength)
        zoom_end = min(zoom_end, MAX_ZOOM)
        zoom_start = max(1.0, min(zoom_start, zoom_end))
        duration = float(params.get("editing_window", 0) or 0) or clip.duration
        w, h = clip.size

        def size_at(t):
            frac = min(1.0, max(0.0, t / max(duration, 0.01)))
            frac = frac * frac * (3.0 - 2.0 * frac)
            scale = zoom_start + (zoom_end - zoom_start) * frac
            return (max(w, int(round(w * scale))), max(h, int(round(h * scale))))

        logger.debug("ken_burns/slow_zoom: %.2f→%.2f over %.2fs", zoom_start, zoom_end, duration)
        zoomed = clip.with_effects([vfx.Resize(size_at)])
        return lock_clip_size(zoomed, w, h).with_duration(clip.duration)
