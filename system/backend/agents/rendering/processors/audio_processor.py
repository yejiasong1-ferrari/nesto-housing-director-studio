"""Audio Processor — build a non-overlapping narration track.

Narration is placed on a global timeline so CrossFade video overlaps
never stack two voice lines on top of each other.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TAIL_PAD = 0.25


def probe_audio_duration(path: str, fallback: float = 0.0) -> float:
    """Return the real on-disk duration of an audio file (ffprobe first)."""
    if not path or not Path(path).exists():
        return float(fallback or 0.0)
    try:
        from backend.tools.audio_utils import get_audio_duration

        probed = get_audio_duration(Path(path))
        if probed > 0.05:
            return probed
    except Exception:
        pass
    try:
        from mutagen.mp3 import MP3
        return float(MP3(path).info.length)
    except Exception:
        pass
    try:
        from moviepy import AudioFileClip
        clip = AudioFileClip(path)
        dur = float(clip.duration or 0)
        clip.close()
        return dur
    except Exception as exc:
        logger.debug("probe_audio_duration failed for %s: %s", path, exc)
        return float(fallback or 0.0)


class AudioProcessor:
    """Layer narration audio onto a video clip OR build a global track."""

    def mix(self, clip, audio_path: str, audio_duration: float) -> object:
        """Legacy per-clip mix (kept for tests). Prefer build_timeline_audio."""
        if not audio_path or not Path(audio_path).exists():
            logger.warning("Audio not found: %s — silent clip", audio_path)
            return clip.without_audio()

        from moviepy import AudioFileClip

        narration = AudioFileClip(audio_path)
        if narration.duration > clip.duration + 0.05:
            logger.warning(
                "Narration (%.2fs) longer than clip (%.2fs) — keeping full audio; "
                "extend clip upstream",
                narration.duration, clip.duration,
            )
        return clip.with_audio(narration.with_start(0))

    def build_timeline_audio(
        self,
        segments: list[dict],
        total_duration: float,
    ) -> tuple[Any, list[dict[str, Any]]]:
        """Compose one AudioClip from segment narrations.

        segments: list of dicts with keys:
          audio_path, audio_duration, timeline_start, editing_window

        Returns (composite_audio, placements) where placements mirror what was
        actually mixed — including cursor_guard delays and real file durations.
        """
        from moviepy import AudioClip, AudioFileClip, CompositeAudioClip

        parts = []
        placements: list[dict[str, Any]] = []
        cursor_guard = 0.0  # ensure no overlap even if timeline_start collides

        for seg in segments:
            path = (seg.get("audio_path") or "").strip()
            if not path or not Path(path).exists():
                continue
            intended = float(seg.get("timeline_start", 0) or 0)
            # Push start forward if previous narration would still be speaking
            start = max(intended, cursor_guard)

            narr = AudioFileClip(path)
            # Always trust the real file length — metadata audio_duration has
            # been observed at ~½× for some TTS mp3s, which desyncs the Studio.
            real_dur = float(narr.duration or 0)
            meta_dur = float(seg.get("audio_duration", 0) or 0)
            if meta_dur > 0.1 and real_dur > meta_dur * 1.5 + 0.3:
                logger.warning(
                    "Audio metadata duration %.2fs << file %.2fs for %s — using file duration",
                    meta_dur, real_dur, Path(path).name,
                )

            narr = narr.with_start(start)
            parts.append(narr)
            cursor_guard = start + real_dur + 0.05
            placements.append({
                "audio_path": path,
                "timeline_start": round(start, 3),
                "intended_start": round(intended, 3),
                "audio_duration": round(real_dur, 3),
                "segment_id": seg.get("segment_id", ""),
            })
            logger.info(
                "Audio place %s @ %.2fs (file=%.2fs, meta=%.2fs, intended=%.2fs)",
                Path(path).name, start, real_dur, meta_dur, intended,
            )

        if not parts:
            silent = AudioClip(lambda t: 0, duration=max(total_duration, 0.1), fps=44100)
            return silent, placements

        composite = CompositeAudioClip(parts)
        final_dur = max(total_duration, cursor_guard + TAIL_PAD)
        if composite.duration < final_dur:
            composite = composite.with_duration(final_dur)
        return composite, placements
