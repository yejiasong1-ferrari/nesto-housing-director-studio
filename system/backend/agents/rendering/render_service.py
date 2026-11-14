"""Render Service — deterministic MoviePy rendering pipeline.

Input:  source video path + EditingPlan + workflow AudioConfig
Output: final MP4

Pipeline:
  For each EditingSegmentPlan:
    1. ClipProcessor     — extract + resize (+ extend if audio longer)
    2. EffectProcessor   — slow_motion / slow_zoom / zoom / freeze / ken_burns
    3. SubtitleProcessor — PIL subtitle overlay
  Then:
    4. TransitionProcessor — concatenate VIDEO only (mild crossfades)
    5. AudioProcessor      — global narration track (no overlap / no cutoff)
    6. AudioMixer          — narration + fixed default BGM
    7. write_videofile
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from backend.agents.rendering.audio.mixer import AudioMixer
from backend.agents.rendering.processors.audio_processor import AudioProcessor
from backend.agents.rendering.processors.clip_processor import ClipProcessor
from backend.agents.rendering.processors.effect_processor import EffectProcessor
from backend.agents.rendering.processors.subtitle_processor import SubtitleProcessor
from backend.agents.rendering.processors.transition_processor import TransitionProcessor
from backend.schemas.audio_schema import AudioConfig, DEFAULT_BGM_VOLUME_DB
from backend.schemas.editing_schema import EditingPlan
from backend.schemas.render_schema import RenderResult, RenderSegmentResult, StudioTimingSegment

logger = logging.getLogger(__name__)

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
OUTPUT_FPS = 30
AUDIO_TAIL_PAD = 0.40


class RenderService:
    """Execute the full rendering pipeline."""

    def __init__(
        self,
        output_width: int = OUTPUT_WIDTH,
        output_height: int = OUTPUT_HEIGHT,
        fps: int = OUTPUT_FPS,
        preserve_full_span: bool = True,
    ) -> None:
        self.output_size = (output_width, output_height)
        self.fps = fps
        self.preserve_full_span = preserve_full_span
        self.clip_proc = ClipProcessor()
        self.effect_proc = EffectProcessor(preserve_full_span=preserve_full_span)
        self.audio_proc = AudioProcessor()
        self.audio_mixer = AudioMixer()
        self.subtitle_proc = SubtitleProcessor()
        self.transition_proc = TransitionProcessor()

    def render(
        self,
        source_video_path: str | Path,
        editing_plan: EditingPlan | dict,
        output_path: str | Path,
        audio_config: AudioConfig | dict[str, Any] | None = None,
    ) -> RenderResult:
        from moviepy import VideoFileClip

        if isinstance(editing_plan, dict):
            editing_plan = EditingPlan.model_validate(editing_plan)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "RenderService: loading source '%s' → %d segments → '%s'",
            Path(source_video_path).name,
            len(editing_plan.segments),
            output_path.name,
        )

        source = VideoFileClip(str(source_video_path))
        # Match canvas orientation to source (portrait → 1080×1920) and
        # letterbox inside ClipProcessor — restores natural proportions.
        self.output_size = ClipProcessor.resolve_canvas(source.size)
        segment_results: list[RenderSegmentResult] = []
        clips_with_transitions: list[tuple] = []
        audio_cues: list[dict] = []
        video_cursor = 0.0
        layout_cursor = 0.0
        # Provisional timing — finalized after audio placement (cursor_guard).
        provisional: list[dict] = []

        from backend.agents.rendering.processors.audio_processor import probe_audio_duration

        # Mirror AudioProcessor.cursor_guard so the VIDEO clock is coupled to the
        # NARRATION clock: the next scene's video never starts before the current
        # narration has finished (+ tail). Prevents audio bleeding across scenes
        # and "audio starts before the picture arrives" (mis-attributed bleed).
        narr_guard = 0.0

        try:
            for i, seg_plan in enumerate(editing_plan.segments):
                logger.info(
                    "  [%d/%d] %s %s | %.1fs–%.1fs effect=%s",
                    i + 1, len(editing_plan.segments),
                    seg_plan.segment_id,
                    seg_plan.role,
                    seg_plan.video_start,
                    seg_plan.video_end,
                    seg_plan.primary_strategy().type,
                )

                # Predict narration timing BEFORE building the clip so the visual
                # window can be stretched to cover it (deterministic execution).
                audio_path = (seg_plan.audio_path or "").strip()
                pre_audio_dur = probe_audio_duration(
                    audio_path, float(seg_plan.audio_duration or 0)
                ) or float(seg_plan.audio_duration or 0)
                raw_offset = float(getattr(seg_plan, "audio_offset", 0.0) or 0.0)
                predicted_start = max(video_cursor + raw_offset, narr_guard)
                min_window = 0.0
                if pre_audio_dur > 0:
                    # window must last from clip start until narration end + tail
                    min_window = (predicted_start - video_cursor) + pre_audio_dur + AUDIO_TAIL_PAD

                clip, seg_result, audio_meta = self._render_segment(
                    source, seg_plan, min_window=min_window
                )
                t_dur = float(seg_plan.transition_duration or 0)
                t_type = seg_plan.transition_type or "cut"
                if self.preserve_full_span:
                    # Overlap transitions discard frames — force hard cuts
                    t_type, t_dur = "cut", 0.0
                elif clip.duration < 1.5:
                    t_type, t_dur = "cut", 0.0

                clips_with_transitions.append((clip, t_type, t_dur))
                segment_results.append(seg_result)

                meta_dur = float(audio_meta.get("audio_duration", 0) or 0)
                audio_dur = probe_audio_duration(audio_path, meta_dur) or meta_dur
                # Preserve Vision's "room is visible before VO starts" onset.
                # If audio is still too long, the timeline/post-TTS guard must
                # shorten it; rendering must not pull the line back into the
                # hallway or previous room.
                offset = max(0.0, raw_offset)

                # Narration start on the global track (coupled anti-overlap).
                start = max(video_cursor + offset, narr_guard)
                audio_cues.append({
                    "segment_id": seg_plan.segment_id,
                    "audio_path": audio_path,
                    "audio_duration": audio_dur,
                    "timeline_start": start,
                    "editing_window": clip.duration,
                })
                provisional.append({
                    "id": seg_plan.segment_id,
                    "layout_start": layout_cursor,
                    "clip_duration": float(clip.duration),
                    "video_start": video_cursor,
                    "audio_offset": offset,
                    "audio_duration": audio_dur,
                })

                if audio_dur > 0:
                    narr_guard = start + audio_dur + 0.05

                next_overlap = 0.0
                if not self.preserve_full_span and t_type in (
                    "dissolve", "soft_pan", "camera_pan"
                ):
                    next_overlap = min(t_dur, 0.35)
                layout_cursor += float(clip.duration)
                video_cursor += max(0.1, float(clip.duration) - next_overlap)

            logger.info("Concatenating %d clips with transitions...", len(clips_with_transitions))
            final = self.transition_proc.concatenate(clips_with_transitions)

            narration_audio, placements = self.audio_proc.build_timeline_audio(
                audio_cues, total_duration=final.duration,
            )
            place_by_id = {p.get("segment_id"): p for p in placements if p.get("segment_id")}

            # Finalize Studio timing from what was actually mixed into the MP4.
            studio_timing: list[StudioTimingSegment] = []
            layout_cursor = 0.0
            for prov in provisional:
                placed = place_by_id.get(prov["id"]) or {}
                audio_dur = float(placed.get("audio_duration") or prov["audio_duration"] or 0)
                narr_at = float(placed.get("timeline_start") or (prov["video_start"] + prov["audio_offset"]))
                offset = float(prov["audio_offset"])
                clip_dur = float(prov["clip_duration"])
                # Layout window must cover the full narration so the playhead
                # doesn't enter the next scene while this line is still speaking.
                layout_dur = max(clip_dur, offset + audio_dur + 0.05)
                studio_timing.append(StudioTimingSegment(
                    id=prov["id"],
                    layout_start=round(layout_cursor, 3),
                    layout_duration=round(layout_dur, 3),
                    video_start=round(float(prov["video_start"]), 3),
                    video_duration=round(clip_dur, 3),
                    narration_at=round(narr_at, 3),
                    audio_offset=round(offset, 3),
                    audio_duration=round(audio_dur, 3),
                ))
                layout_cursor += layout_dur

            if narration_audio.duration > final.duration + 0.05:
                # Prefer continuous slow-mo over a frozen still at the end.
                target = narration_audio.duration + AUDIO_TAIL_PAD
                logger.info(
                    "Extending final video %.2fs → %.2fs via slow-motion",
                    final.duration, target,
                )
                final = self.effect_proc.apply(
                    final, "slow_motion",
                    {"editing_window": target, "allow_freeze": False},
                )

            final_audio, bgm_meta = self.audio_mixer.mix(
                narration_audio,
                target_duration=final.duration,
                audio_config=audio_config,
            )
            final = final.with_audio(final_audio)

            # Letterbox + slow_zoom can leave a mask one pixel wider than the
            # RGB frame. Export only needs the already-composited picture.
            if getattr(final, "mask", None) is not None:
                final = final.without_mask()

            logger.info(
                "Exporting to %s (%.1fs, %dx%d @ %dfps)...",
                output_path, final.duration, *self.output_size, self.fps,
            )
            final.write_videofile(
                str(output_path),
                fps=self.fps,
                codec="libx264",
                audio_codec="aac",
                audio_bitrate="192k",
                preset="medium",
                ffmpeg_params=[
                    "-vsync", "cfr",
                    "-crf", "18",
                    "-movflags", "+faststart",
                ],
                logger=None,
            )

            total_dur = final.duration
            file_size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info("Render complete: %.1fs %.1fMB → %s", total_dur, file_size_mb, output_path)

            timing_path = output_path.with_name("studio_timing.json")
            timing_payload = {
                "duration": round(total_dur, 3),
                "layout_duration": round(layout_cursor, 3),
                "segments": [s.model_dump() for s in studio_timing],
            }
            timing_path.write_text(
                __import__("json").dumps(timing_payload, indent=2),
                encoding="utf-8",
            )

            return RenderResult(
                project_id=editing_plan.project_id,
                status="success",
                output_path=str(output_path),
                duration=round(total_dur, 2),
                fps=self.fps,
                width=self.output_size[0],
                height=self.output_size[1],
                file_size_mb=round(file_size_mb, 2),
                segments=segment_results,
                studio_timing=studio_timing,
                bgm_mixed=bool(bgm_meta.get("bgm_mixed")),
                bgm_path=str(bgm_meta.get("bgm_path") or ""),
                bgm_volume_db=float(
                    bgm_meta.get("bgm_volume_db")
                    if bgm_meta.get("bgm_volume_db") is not None
                    else DEFAULT_BGM_VOLUME_DB
                ),
            )

        except Exception as exc:
            logger.error("Render failed: %s", exc, exc_info=True)
            return RenderResult(
                project_id=editing_plan.project_id,
                status="failed",
                error=str(exc),
            )
        finally:
            source.close()

    def remix_audio_only(
        self,
        input_video_path: str | Path,
        editing_plan: EditingPlan | dict,
        output_path: str | Path,
        *,
        audio_config: AudioConfig | dict[str, Any] | None = None,
        studio_timing_path: str | Path | None = None,
        prior_render: RenderResult | dict[str, Any] | None = None,
    ) -> RenderResult:
        """Apply an audio-only feedback fix without re-encoding video.

        This path is intentionally narrow: callers may use it only when
        evaluation changed BGM configuration and did not change narration,
        timing, subtitles, effects, or editing windows. The H.264 stream is
        copied bit-for-bit; only the AAC mix is rebuilt.
        """
        from backend.tools.video_utils import get_video_duration

        if isinstance(editing_plan, dict):
            editing_plan = EditingPlan.model_validate(editing_plan)
        input_path = Path(input_video_path)
        output_path = Path(output_path)
        if not input_path.exists():
            raise FileNotFoundError(str(input_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        timing_path = Path(studio_timing_path) if studio_timing_path else (
            input_path.with_name("studio_timing.json")
        )
        if not timing_path.exists():
            raise FileNotFoundError(f"Studio timing not found: {timing_path}")
        timing_payload = json.loads(timing_path.read_text(encoding="utf-8"))
        timing_by_id = {
            str(item.get("id") or ""): item
            for item in (timing_payload.get("segments") or [])
            if item.get("id")
        }

        duration = get_video_duration(input_path)
        if duration <= 0:
            duration = float(timing_payload.get("duration") or 0)
        if duration <= 0:
            raise RuntimeError(f"Could not probe video duration: {input_path}")

        cues: list[dict[str, Any]] = []
        for seg in editing_plan.segments:
            timing = timing_by_id.get(seg.segment_id)
            if not timing:
                raise RuntimeError(
                    f"Missing studio timing for audio-only remix: {seg.segment_id}"
                )
            cues.append({
                "segment_id": seg.segment_id,
                "audio_path": (seg.audio_path or "").strip(),
                "audio_duration": float(
                    timing.get("audio_duration") or seg.audio_duration or 0
                ),
                "timeline_start": float(
                    timing.get("narration_at")
                    if timing.get("narration_at") is not None
                    else timing.get("video_start", 0)
                ),
                "editing_window": float(timing.get("video_duration") or 0),
            })

        narration_audio = None
        mixed_audio = None
        temp_audio = output_path.with_name(f".{output_path.stem}.remix.m4a")
        try:
            narration_audio, _placements = self.audio_proc.build_timeline_audio(
                cues, total_duration=duration,
            )
            mixed_audio, bgm_meta = self.audio_mixer.mix(
                narration_audio,
                target_duration=duration,
                audio_config=audio_config,
            )
            mixed_audio = mixed_audio.with_duration(duration)
            mixed_audio.write_audiofile(
                str(temp_audio),
                fps=44100,
                codec="aac",
                bitrate="192k",
                logger=None,
            )

            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-i", str(temp_audio),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "copy",
                "-map_metadata", "0",
                "-t", f"{duration:.6f}",
                "-movflags", "+faststart",
                str(output_path),
            ]
            logger.info(
                "Audio-only remix: video stream copy %s → %s (%.2fs)",
                input_path.name,
                output_path.name,
                duration,
            )
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(120, int(duration * 2)),
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg audio remux failed: {result.stderr[-800:]}")
        finally:
            if mixed_audio is not None:
                mixed_audio.close()
            if narration_audio is not None and narration_audio is not mixed_audio:
                narration_audio.close()
            temp_audio.unlink(missing_ok=True)

        base = (
            prior_render
            if isinstance(prior_render, RenderResult)
            else RenderResult.model_validate(prior_render or {})
        )
        return base.model_copy(update={
            "output_path": str(output_path),
            "duration": round(duration, 2),
            "file_size_mb": round(output_path.stat().st_size / (1024 * 1024), 2),
            "bgm_mixed": bool(bgm_meta.get("bgm_mixed")),
            "bgm_path": str(bgm_meta.get("bgm_path") or ""),
            "bgm_volume_db": float(
                bgm_meta.get("bgm_volume_db")
                if bgm_meta.get("bgm_volume_db") is not None
                else DEFAULT_BGM_VOLUME_DB
            ),
            "status": "success",
            "error": "",
        })

    def _render_segment(self, source, seg_plan, min_window: float = 0.0) -> tuple:
        effects_applied: list[str] = []

        # Resolve how long this visual window must be
        audio_path = (seg_plan.audio_path or "").strip()
        audio_dur = float(seg_plan.audio_duration or 0)
        if audio_path and Path(audio_path).exists() and audio_dur <= 0:
            try:
                from moviepy import AudioFileClip
                ac = AudioFileClip(audio_path)
                audio_dur = float(ac.duration)
                ac.close()
            except Exception:
                audio_dur = 0.0

        video_span = max(0.1, float(seg_plan.video_end) - float(seg_plan.video_start))
        target_window = float(seg_plan.editing_window or 0) or video_span
        if audio_dur > 0:
            target_window = max(target_window, audio_dur + AUDIO_TAIL_PAD)
        # One-shot walkthrough: never schedule a window shorter than the extract
        if self.preserve_full_span:
            target_window = max(target_window, video_span)
        # Coupling from render loop: hold this scene until its narration ends
        # (includes slip inherited from a previous over-running narration).
        if min_window and min_window > 0:
            target_window = max(target_window, min_window)

        # 1. Extract clip
        clip = self.clip_proc.extract(
            source,
            seg_plan.video_start,
            seg_plan.video_end,
            self.output_size,
        )

        # 2. Apply primary visual effect (may change duration for slow_motion)
        strategy = seg_plan.primary_strategy()
        params = dict(strategy.parameters or {})
        # In-space A/V fill: continuous slow-motion only — never pause/freeze
        # while narration finishes. Single MultiplySpeed remap avoids CFR
        # "dropped frame" stutter from freeze + speed stacking.
        fill_params = {
            "editing_window": target_window,
            "allow_freeze": False,
        }
        if target_window > clip.duration + 0.05 and strategy.type in (
            "clean_cut", "zoom", "slow_zoom", "ken_burns", "freeze_frame", ""
        ):
            if strategy.type in ("slow_zoom", "ken_burns", "zoom"):
                clip = self.effect_proc.apply(
                    clip, strategy.type or "slow_zoom",
                    {**params, "editing_window": target_window},
                )
                effects_applied.append(strategy.type or "slow_zoom")
                if clip.duration + 0.05 < target_window:
                    clip = self.effect_proc.apply(clip, "slow_motion", fill_params)
                    effects_applied.append("slow_motion")
            else:
                # clean_cut / freeze_frame / unset → slow-mo fill (no pause)
                clip = self.effect_proc.apply(clip, "slow_motion", fill_params)
                effects_applied.append("slow_motion")
        elif strategy.type and strategy.type != "clean_cut":
            params.setdefault("editing_window", target_window)
            params.setdefault("allow_freeze", False)
            if strategy.type == "freeze_frame" and target_window > clip.duration + 0.05:
                clip = self.effect_proc.apply(clip, "slow_motion", fill_params)
                effects_applied.append("slow_motion")
            else:
                clip = self.effect_proc.apply(clip, strategy.type, params)
                effects_applied.append(strategy.type)

        # Snap duration to target when slightly off — keep motion, no freeze
        if abs(clip.duration - target_window) > 0.08 and target_window > 0:
            if clip.duration < target_window:
                clip = self.effect_proc.apply(clip, "slow_motion", fill_params)
                if "slow_motion" not in effects_applied:
                    effects_applied.append("slow_motion")
            elif not self.preserve_full_span:
                # Legacy path only — continuous mode never hard-trims footage
                clip = clip.with_duration(target_window)
            else:
                logger.debug(
                    "preserve_full_span: keeping %.2fs clip (target was %.2fs)",
                    clip.duration,
                    target_window,
                )

        # 3. Burn subtitles (video only — audio mixed globally later)
        subtitle_burned = False
        sub = seg_plan.subtitle
        sub_enabled = bool(getattr(sub, "enabled", True))
        if sub_enabled and (seg_plan.narration_text or "").strip():
            clip = self.subtitle_proc.add(clip, seg_plan.narration_text, sub)
            subtitle_burned = True

        try:
            clip = clip.without_audio()
        except Exception:
            pass

        audio_mixed = bool(audio_path and Path(audio_path).exists())
        seg_result = RenderSegmentResult(
            segment_id=seg_plan.segment_id,
            duration=round(clip.duration, 2),
            effects_applied=effects_applied,
            audio_mixed=audio_mixed,
            subtitle_burned=subtitle_burned,
        )
        audio_meta = {
            "audio_path": audio_path if audio_mixed else "",
            "audio_duration": audio_dur,
        }
        return clip, seg_result, audio_meta
