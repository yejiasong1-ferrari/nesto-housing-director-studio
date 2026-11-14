"""Audio Mixer — narration (0 dB) + low-volume BGM.

Narration always wins. BGM is a fixed underlay from workflow AudioConfig.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.agents.rendering.audio.bgm_handler import BGMHandler
from backend.schemas.audio_schema import AudioConfig, BackgroundMusicConfig

logger = logging.getLogger(__name__)


def db_to_linear(volume_db: float) -> float:
    """Convert dB gain to MoviePy MultiplyVolume factor."""
    return float(10.0 ** (volume_db / 20.0))


class AudioMixer:
    """Mix narration track with optional fixed BGM."""

    def __init__(self, bgm_handler: BGMHandler | None = None) -> None:
        self.bgm_handler = bgm_handler or BGMHandler()

    def mix(
        self,
        narration,
        *,
        target_duration: float,
        audio_config: AudioConfig | dict[str, Any] | None = None,
    ):
        """Return final CompositeAudioClip: narration + ducked BGM."""
        cfg = self._normalize_config(audio_config)
        bgm_cfg = cfg.background_music

        if narration is None:
            from moviepy import AudioClip
            narration = AudioClip(
                lambda t: 0, duration=max(target_duration, 0.1), fps=44100
            )

        # Narration at full level (0 dB reference)
        final_dur = max(
            float(target_duration or 0),
            float(getattr(narration, "duration", 0) or 0),
            0.1,
        )
        if getattr(narration, "duration", 0) and narration.duration < final_dur:
            narration = narration.with_duration(final_dur)

        if not bgm_cfg.enabled:
            logger.info("BGM disabled — narration only")
            return narration, {"bgm_mixed": False, "bgm_volume_db": None}

        bgm_path = cfg.resolved_bgm_path()
        if not bgm_path.exists():
            logger.warning("BGM missing at %s — narration only", bgm_path)
            return narration, {
                "bgm_mixed": False,
                "bgm_volume_db": bgm_cfg.volume_db,
                "bgm_path": str(bgm_path),
                "bgm_error": "file_not_found",
            }

        bgm = self._prepare_bgm(bgm_path, final_dur, bgm_cfg)
        from moviepy import CompositeAudioClip

        mixed = CompositeAudioClip([narration, bgm])
        if mixed.duration < final_dur:
            mixed = mixed.with_duration(final_dur)

        meta = {
            "bgm_mixed": True,
            "bgm_path": str(bgm_path),
            "bgm_volume_db": bgm_cfg.volume_db,
            "bgm_linear_gain": round(db_to_linear(bgm_cfg.volume_db), 4),
            "bgm_fade_in": bgm_cfg.fade_in,
            "bgm_fade_out": bgm_cfg.fade_out,
            "bgm_loop": bgm_cfg.loop,
        }
        logger.info(
            "AudioMixer: narration + BGM @ %.1f dB (gain=%.4f) dur=%.2fs",
            bgm_cfg.volume_db,
            meta["bgm_linear_gain"],
            final_dur,
        )
        return mixed, meta

    def _prepare_bgm(self, path: Path, target_duration: float, cfg: BackgroundMusicConfig):
        from moviepy import afx

        bgm = self.bgm_handler.load(path)
        bgm = self.bgm_handler.fit(bgm, target_duration, allow_loop=cfg.loop)

        factor = db_to_linear(cfg.volume_db)
        effects = [afx.MultiplyVolume(factor)]

        fade_in = max(0.0, float(cfg.fade_in or 0))
        fade_out = max(0.0, float(cfg.fade_out or 0))
        # Keep fades inside clip length
        max_fade = max(0.0, target_duration / 2.0 - 0.05)
        fade_in = min(fade_in, max_fade)
        fade_out = min(fade_out, max_fade)
        if fade_in > 0.05:
            effects.append(afx.AudioFadeIn(fade_in))
        if fade_out > 0.05:
            effects.append(afx.AudioFadeOut(fade_out))

        return bgm.with_effects(effects)

    def _normalize_config(
        self, audio_config: AudioConfig | dict[str, Any] | None
    ) -> AudioConfig:
        if audio_config is None:
            return AudioConfig()
        if isinstance(audio_config, AudioConfig):
            return audio_config
        return AudioConfig.model_validate(audio_config)
