"""slow_zoom / resize can leave RGB and mask one pixel apart."""

from __future__ import annotations

import numpy as np

from backend.agents.rendering.processors.effect_processor import (
    crop_or_pad_frame,
    lock_clip_size,
)


def test_crop_or_pad_trims_one_extra_column() -> None:
    frame = np.zeros((1080, 1921, 3), dtype=np.uint8)
    frame[:, 1:, :] = 1
    out = crop_or_pad_frame(frame, 1080, 1920)
    assert out.shape == (1080, 1920, 3)


def test_crop_or_pad_pads_a_short_mask() -> None:
    mask = np.ones((1080, 1919), dtype=np.float32)
    out = crop_or_pad_frame(mask, 1080, 1920)
    assert out.shape == (1080, 1920)


def test_lock_clip_size_matches_frame_and_mask() -> None:
    from moviepy import ColorClip

    clip = ColorClip(size=(1920, 1080), color=(10, 20, 30)).with_duration(0.2)
    # Fake the 1921-wide mask that MoviePy Resize sometimes produces.
    wide = ColorClip(size=(1921, 1080), color=(255, 255, 255)).with_duration(0.2)
    clip = clip.with_mask(wide.to_mask())

    locked = lock_clip_size(clip, 1920, 1080)
    frame = locked.get_frame(0)
    assert frame.shape[0] == 1080 and frame.shape[1] == 1920
    assert locked.size == (1920, 1080)
    if locked.mask is not None:
        mask = locked.mask.get_frame(0)
        assert mask.shape[0] == 1080 and mask.shape[1] == 1920
