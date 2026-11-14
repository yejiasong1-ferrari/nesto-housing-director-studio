"""BGM Handler — load / loop / trim fixed background music.

Deterministic media prep only. No style selection, no LLM.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class BGMHandler:
    """Prepare a BGM clip to match target video duration."""

    def load(self, path: str | Path):
        from moviepy import AudioFileClip

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"BGM not found: {path}")
        clip = AudioFileClip(str(path))
        logger.info("BGM loaded: %s (%.2fs)", path.name, clip.duration)
        return clip

    def fit(self, bgm, target_duration: float, *, allow_loop: bool = True):
        """Loop or trim BGM so its duration matches the video."""
        if target_duration <= 0:
            return bgm.with_duration(0.1)

        bgm_dur = float(bgm.duration or 0)
        if bgm_dur <= 0:
            return bgm.with_duration(target_duration)

        if bgm_dur >= target_duration - 0.05:
            logger.debug("BGM trim %.2fs → %.2fs", bgm_dur, target_duration)
            return bgm.subclipped(0, target_duration)

        if not allow_loop:
            logger.warning(
                "BGM shorter than video (%.2fs < %.2fs) and loop disabled — pad silence",
                bgm_dur, target_duration,
            )
            return bgm.with_duration(target_duration)

        from moviepy import afx

        n_loops = int(target_duration / bgm_dur) + 1
        logger.info(
            "BGM loop %dx (%.2fs → %.2fs)",
            n_loops, bgm_dur, target_duration,
        )
        looped = bgm.with_effects([afx.AudioLoop(n_loops=n_loops)])
        if looped.duration > target_duration:
            looped = looped.subclipped(0, target_duration)
        elif looped.duration < target_duration:
            looped = looped.with_duration(target_duration)
        return looped

    def loop(self, bgm, target_duration: float):
        return self.fit(bgm, target_duration, allow_loop=True)

    def trim(self, bgm, target_duration: float):
        return self.fit(bgm, target_duration, allow_loop=False)
