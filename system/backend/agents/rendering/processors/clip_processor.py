"""Clip Processor — extract and size clips from source video.

Preserves source aspect ratio (letterbox / pillarbox). Canvas orientation
follows the source: landscape → 1920×1080, portrait → 1080×1920 — same
native proportions as v2.2 landscape tours, without stretching vertical
footage into 16:9.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

LANDSCAPE_SIZE = (1920, 1080)
PORTRAIT_SIZE = (1080, 1920)


class ClipProcessor:
    """Extract a subclip and fit it onto the output canvas without distortion."""

    @staticmethod
    def resolve_canvas(source_size: tuple[int, int]) -> tuple[int, int]:
        """Pick output canvas from source orientation."""
        w, h = int(source_size[0]), int(source_size[1])
        if h > w:
            return PORTRAIT_SIZE
        return LANDSCAPE_SIZE

    def extract(
        self,
        source_clip,
        start: float,
        end: float,
        target_size: tuple[int, int],
    ):
        from moviepy import ColorClip, CompositeVideoClip, vfx

        end = min(end, source_clip.duration - 0.05)
        start = max(0.0, start)
        clip = source_clip.subclipped(start, end)

        w, h = int(clip.w), int(clip.h)
        tw, th = int(target_size[0]), int(target_size[1])

        if (w, h) == (tw, th):
            logger.debug("Extracted clip %.2fs–%.2fs → %s (native)", start, end, target_size)
            return clip

        # Fit inside canvas (contain) — never stretch
        scale = min(tw / max(w, 1), th / max(h, 1))
        nw = max(2, int(round(w * scale)))
        nh = max(2, int(round(h * scale)))
        # H.264 prefers even dimensions
        nw -= nw % 2
        nh -= nh % 2

        resized = clip.with_effects([vfx.Resize((nw, nh))])
        if (nw, nh) == (tw, th):
            logger.debug(
                "Extracted clip %.2fs–%.2fs → %s (scaled)",
                start, end, target_size,
            )
            return resized

        bg = ColorClip(size=(tw, th), color=(0, 0, 0)).with_duration(resized.duration)
        x = (tw - nw) // 2
        y = (th - nh) // 2
        composed = CompositeVideoClip(
            [bg, resized.with_position((x, y))],
            size=(tw, th),
        ).with_duration(resized.duration)

        logger.debug(
            "Extracted clip %.2fs–%.2fs → %s (fit %dx%d letterbox)",
            start, end, target_size, nw, nh,
        )
        return composed
