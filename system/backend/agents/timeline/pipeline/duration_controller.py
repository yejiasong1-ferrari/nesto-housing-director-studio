"""Module 3: Duration Controller.

Resolves the voice duration vs video duration mismatch for each segment group.

Decision tree (per merged group):
  occupied = audio_offset + audio_duration   (when VO actually finishes)
  delta = audio_duration - video_duration   (positive → audio longer)

  If delayed entry leaves too little speakable window → rewrite shorter.
  Never move the opening earlier to make room for a long line.

  |delta| <= TOLERANCE (and occupied fits):
    → NO_ADJUSTMENT; editing_window covers video and offset+audio+pad

  audio > video (delta > TOLERANCE):
    Within a space we prefer continuous slow-motion so narration finishes
    while footage keeps moving (no freeze-frame pause).
    importance >= HIGH_THRESHOLD:
      speed >= COMFORTABLE_MIN_SPEED → SLOW_MOTION
      else → SLOW_MOTION + FLAG_REWRITE (compress narration; still slow-mo)
    importance < HIGH_THRESHOLD:
      → FLAG_REWRITE (editing_window = audio; needs_script_rewrite)
        (Rendering may still slow-mo if rewrite cannot close the gap)

  video > audio (delta < -TOLERANCE):
    importance >= LOW_THRESHOLD:
      → TRIM_VIDEO; editing_window = video_duration
        (keep full span — name is historical; footage is NOT cut)
    else:
      → TRIM_VIDEO / INSERT_VISUAL_ACCENT; editing_window = video_duration
"""

from __future__ import annotations

import logging

from backend.agents.timeline.pipeline.analyzer import EnrichedSegment
from backend.agents.timeline.pipeline.segment_optimizer import MergeGroup
from backend.schemas.timeline_schema import DurationAdjustmentStrategy, DurationDecision

logger = logging.getLogger(__name__)

TOLERANCE = 0.5       # seconds — within this → no adjustment
# Prefer slow-mo while playback stays visually smooth (~>= 0.50x).
COMFORTABLE_MIN_SPEED = 0.50
HIGH_IMPORTANCE = 0.65
LOW_IMPORTANCE = 0.35
# A 4s dishwasher close-up stretched to cover a sentence reads as padding.
# Compress the line instead of the picture.
MIN_SLOWMO_SOURCE = 6.0
# Pad so the last syllable is never clipped by a hard cut / transition
AUDIO_TAIL_PAD = 0.40


class DurationController:
    """Decide the duration strategy and final editing window for each group."""

    def decide(self, group: MergeGroup) -> DurationDecision:
        audio_duration = self._group_audio(group)
        video_duration = self._group_video(group)
        importance = max(s.importance for s in group.segments)
        audio_offset = self._group_offset(group)
        occupied = audio_offset + audio_duration
        needed = occupied + AUDIO_TAIL_PAD if audio_duration > 0 else video_duration
        target_audio = self._group_speakable_audio(group, audio_offset)

        delta = audio_duration - video_duration

        if (
            audio_offset > 0.05
            and audio_duration > 0
            and audio_duration > target_audio + TOLERANCE
        ):
            # The camera had to walk into the room first. Keep that wait, and
            # compress the line to what remains in the shot; do not slow the
            # picture or pull narration into the hallway/previous room.
            return DurationDecision(
                strategy=DurationAdjustmentStrategy.FLAG_REWRITE,
                audio_duration=audio_duration,
                video_duration=video_duration,
                delta=round(delta, 2),
                editing_window=round(video_duration, 2),
                extension_factor=1.0,
                needs_script_rewrite=True,
                target_audio_duration=round(target_audio, 2),
            )

        if abs(delta) <= TOLERANCE:
            # Still ensure window covers audio + tail pad (and delayed onset)
            window = max(video_duration, needed if audio_duration > 0 else video_duration)
            strategy = DurationAdjustmentStrategy.NO_ADJUSTMENT
            factor = 1.0
            rewrite = False
            if needed > video_duration + TOLERANCE:
                strategy = DurationAdjustmentStrategy.SLOW_MOTION
                factor = video_duration / needed if needed > 0 else 1.0
                rewrite = False
            return DurationDecision(
                strategy=strategy,
                audio_duration=audio_duration,
                video_duration=video_duration,
                delta=round(delta, 2),
                editing_window=round(window, 2),
                extension_factor=round(factor, 3),
                needs_script_rewrite=rewrite,
                target_audio_duration=round(target_audio, 2),
            )

        if delta > TOLERANCE:
            # audio longer than video
            strategy, factor, window, rewrite = self._resolve_over(
                delta, audio_duration, video_duration, importance
            )
        else:
            # video longer than audio
            strategy, factor, window, rewrite = self._resolve_under(
                delta, audio_duration, video_duration, importance
            )
            if needed > video_duration + TOLERANCE:
                if video_duration < MIN_SLOWMO_SOURCE:
                    strategy = DurationAdjustmentStrategy.FLAG_REWRITE
                    rewrite = True
                else:
                    # Delayed onset made VO overshoot the picture — stretch this
                    # shot. Do not rewrite: the line length is fine, only timing.
                    strategy = DurationAdjustmentStrategy.SLOW_MOTION
                    factor = video_duration / needed if needed > 0 else 1.0
                    rewrite = False

        # Hard guarantee: editing window never shorter than spoken audio + pad
        # or the full source video span (never cut walkthrough footage for time).
        # Also covers delayed onset: window >= offset + audio + pad.
        if audio_duration > 0:
            window = max(window, needed)
        window = max(window, video_duration)

        return DurationDecision(
            strategy=strategy,
            audio_duration=audio_duration,
            video_duration=video_duration,
            delta=round(delta, 2),
            editing_window=round(window, 2),
            extension_factor=round(factor, 3),
            needs_script_rewrite=rewrite,
            target_audio_duration=round(target_audio, 2),
        )

    def _resolve_over(
        self,
        delta: float,
        audio: float,
        video: float,
        importance: float,
    ) -> tuple[DurationAdjustmentStrategy, float, float, bool]:
        window = audio + AUDIO_TAIL_PAD
        factor = video / audio if audio > 0 else 1.0

        if video < MIN_SLOWMO_SOURCE:
            return DurationAdjustmentStrategy.FLAG_REWRITE, factor, window, True

        if importance >= HIGH_IMPORTANCE:
            # Keep motion in-space; rewrite when stretch would look stuttery.
            rewrite = factor < COMFORTABLE_MIN_SPEED
            return DurationAdjustmentStrategy.SLOW_MOTION, factor, window, rewrite

        # Low importance → compress narration first (cognition), not freeze.
        return DurationAdjustmentStrategy.FLAG_REWRITE, factor, window, True

    def _resolve_under(
        self,
        delta: float,
        audio: float,
        video: float,
        importance: float,
    ) -> tuple[DurationAdjustmentStrategy, float, float, bool]:
        gap = abs(delta)
        if gap > 4.0 and importance < LOW_IMPORTANCE:
            # Large gap + low importance → insert a visual accent
            return DurationAdjustmentStrategy.INSERT_VISUAL_ACCENT, 1.0, video, False
        return DurationAdjustmentStrategy.TRIM_VIDEO, 1.0, video, False

    def _group_offset(self, group: MergeGroup) -> float:
        """Narration delay relative to the merged group's picture start."""
        if not group.segments:
            return 0.0
        head = group.segments[0]
        offset = float(getattr(head, "audio_offset", 0.0) or 0.0)
        vis = float(getattr(head, "room_visible_start", 0.0) or 0.0)
        start = float(head.video_start or 0.0)
        if vis > 0.0 or start <= 0.5:
            offset = max(offset, vis - start)
        return max(0.0, offset)

    def _group_visible_end(self, group: MergeGroup) -> float:
        """Last absolute time the group's primary room is still the shot."""
        if not group.segments:
            return 0.0
        tail = group.segments[-1]
        vis = float(getattr(tail, "room_visible_end", 0.0) or 0.0)
        end = float(tail.video_end or 0.0)
        if vis <= 0.0:
            return end
        start = float(group.segments[0].video_start or 0.0)
        return min(max(vis, start), end)

    def _group_speakable_audio(self, group: MergeGroup, audio_offset: float) -> float:
        """Available VO seconds after the room is visible, before the cut."""
        video = self._group_video(group)
        visible_end = self._group_visible_end(group)
        start = float(group.segments[0].video_start or 0.0) if group.segments else 0.0
        if visible_end > start:
            video = min(video, max(0.0, visible_end - start))
        return max(0.0, video - max(0.0, audio_offset) - AUDIO_TAIL_PAD)

    def _group_audio(self, group: MergeGroup) -> float:
        """Sum audio durations, using actual if available, else estimated."""
        total = 0.0
        for seg in group.segments:
            total += seg.audio_duration if seg.audio_duration > 0 else seg.estimated_duration
        return total

    def _group_video(self, group: MergeGroup) -> float:
        """Full source span of the merged group (end − start), including gaps."""
        if not group.segments:
            return 0.0
        start = group.segments[0].video_start
        end = group.segments[-1].video_end
        span = max(0.0, float(end) - float(start))
        if span > 0:
            return span
        return sum(s.video_duration for s in group.segments)
