"""Transition Processor — MoviePy 2.x crossfade / fade transitions.

Uses short, mild overlaps to avoid stutter. Audio is mixed separately
so visual crossfades never cause narration overlap.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Cap visual overlap — long crossfades look stuttery on walkthrough footage
MAX_CROSSFADE = 0.35


class TransitionProcessor:
    """Assemble clips with the correct transition between them."""

    def concatenate(
        self,
        clips_with_transitions: list[tuple],
    ) -> object:
        """
        clips_with_transitions: list of (clip, transition_type, transition_duration)
        Returns final concatenated VIDEO clip (audio stripped — mixed later).
        """
        from moviepy import concatenate_videoclips, vfx

        if not clips_with_transitions:
            raise ValueError("No clips to concatenate")

        # Strip audio from visual clips — narration is a separate track
        stripped = []
        for clip, t_type, t_dur in clips_with_transitions:
            try:
                clip = clip.without_audio()
            except Exception:
                pass
            t_dur = min(float(t_dur or 0), MAX_CROSSFADE) if t_dur else 0.0
            # Hard cuts for very short clips — crossfade needs headroom
            if clip.duration < 1.2:
                t_type, t_dur = "cut", 0.0
            stripped.append((clip, t_type, t_dur))

        if len(stripped) == 1:
            return stripped[0][0]

        processed: list = []
        for i, (clip, t_type, t_dur) in enumerate(stripped):
            is_last = i == len(stripped) - 1

            if not is_last and t_dur > 0:
                if t_type in ("dissolve", "soft_pan", "camera_pan"):
                    clip = clip.with_effects([vfx.CrossFadeOut(t_dur)])
                elif t_type == "fade":
                    clip = clip.with_effects([vfx.FadeOut(min(t_dur, 0.4))])

            if i > 0:
                prev_type = stripped[i - 1][1]
                prev_dur = stripped[i - 1][2]
                if prev_dur > 0 and prev_type in ("dissolve", "soft_pan", "camera_pan"):
                    clip = clip.with_effects([vfx.CrossFadeIn(prev_dur)])
                elif prev_dur > 0 and prev_type == "fade":
                    clip = clip.with_effects([vfx.FadeIn(min(prev_dur, 0.4))])

            processed.append(clip)

        padding_list: list[float] = []
        for i in range(len(processed) - 1):
            _, t_type, t_dur = stripped[i]
            if t_type in ("dissolve", "soft_pan", "camera_pan") and t_dur > 0:
                padding_list.append(-t_dur)
            else:
                padding_list.append(0.0)

        if all(p == 0.0 for p in padding_list):
            return concatenate_videoclips(processed, method="chain")

        result = processed[0]
        for i, clip in enumerate(processed[1:]):
            pad = padding_list[i]
            if pad < 0:
                result = concatenate_videoclips(
                    [result, clip], padding=pad, method="compose"
                )
            else:
                result = concatenate_videoclips([result, clip], method="chain")

        return result
