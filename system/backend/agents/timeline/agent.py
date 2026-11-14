"""Timeline Agent — Narrative Temporal Director.

Synthesises Vision + Planner + Script + Voice into a single executable
cinematic time structure. First agent that has all four inputs simultaneously.

Pipeline (all rule-based, no LLM):
  Module 1: TimelineAnalyzer        — unified EnrichedSegment list
  Module 2: SegmentOptimizer        — merge scoring (5-factor weighted)
  Module 3: DurationController      — voice vs video decision tree
  Module 4: NarrativeFlowController — story phases + cinematic pacing
  Module 5: TransitionPlanner       — inter-segment transitions
  Module 6: TimelineValidator       — timing, coverage, duplicate checks

Output: TimelineOutput consumed by Editing Strategy Agent.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agents.timeline.pipeline.analyzer import TimelineAnalyzer
from backend.agents.timeline.pipeline.duration_controller import DurationController
from backend.agents.timeline.pipeline.narrative_flow import NarrativeFlowController
from backend.agents.timeline.pipeline.segment_optimizer import MergeGroup, SegmentOptimizer
from backend.agents.timeline.pipeline.transition_planner import TransitionPlanner
from backend.agents.timeline.validators.timeline_validator import TimelineValidator
from backend.core.base_agent import BaseAgent
from backend.schemas.timeline_schema import (
    MergeInfo,
    NarrationInfo,
    SourceTiming,
    TimelineOutput,
    TimelineSegment,
    TransitionPlan,
)
from backend.state.project_state import ProjectState

logger = logging.getLogger(__name__)


class TimelineAgent(BaseAgent):
    """Narrative Temporal Director — organises the cinematic time structure."""

    agent_name = "timeline"
    state_key = "timeline"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.continuous_walkthrough = bool(
            (config or {}).get("continuous_walkthrough", True)
        )
        self.analyzer = TimelineAnalyzer()
        self.optimizer = SegmentOptimizer()
        self.duration_ctrl = DurationController()
        self.flow_ctrl = NarrativeFlowController()
        self.transition_planner = TransitionPlanner(
            continuous_walkthrough=self.continuous_walkthrough
        )
        self.validator = TimelineValidator()

    async def run(self, state: ProjectState) -> ProjectState:
        vkb = state.vision or {}
        planning = state.planning or {}
        script = state.script or {}
        voice_raw = state.voice or {}

        voice_plan = voice_raw if "voice_plan" in voice_raw else {}
        voice_execution: dict[str, Any] = {}
        if "segments" in voice_raw and voice_raw.get("agent_name") == "voice_execution":
            voice_execution = voice_raw
        elif "segments" in voice_raw:
            voice_execution = voice_raw

        if not script.get("narration_segments"):
            raise ValueError("Script output is required but narration_segments is empty")

        hero_ids: list[str] = (
            planning.get("hierarchy", {}).get("hero_segments", [])
        )

        logger.info(
            "Timeline Agent: %d script segments | %d HERO",
            len(script.get("narration_segments", [])),
            len(hero_ids),
        )

        # Module 1: Analyze
        enriched = self.analyzer.analyze(vkb, planning, script, voice_plan, voice_execution)

        # Module 2: Segment Optimizer
        groups = self.optimizer.optimize(enriched)
        merge_count = sum(1 for g in groups if len(g.segments) > 1)
        logger.info("Optimizer: %d groups from %d segments (%d merges)", len(groups), len(enriched), merge_count)

        # Modules 3-5: per group
        duration_decisions = [self.duration_ctrl.decide(g) for g in groups]
        visual_plans = self.flow_ctrl.plan(groups, total_groups=len(groups))
        transitions_raw = self.transition_planner.plan_all(groups)

        # Assemble TimelineSegments
        segments: list[TimelineSegment] = []
        cursor = 0.0
        for i, (group, dur_dec, vis_plan, trans_raw) in enumerate(
            zip(groups, duration_decisions, visual_plans, transitions_raw)
        ):
            head = group.segments[0]
            source_ids = [s.segment_id for s in group.segments]

            tl_id = self._make_id(i + 1, source_ids)
            is_merged = len(group.segments) > 1

            narration_text = " ".join(s.narration_text for s in group.segments if s.narration_text)
            tts_text = " ".join(s.tts_text for s in group.segments if s.tts_text)
            audio_path = head.audio_path
            if is_merged and group.segments[1].audio_path:
                audio_path = group.segments[0].audio_path

            merge_info = MergeInfo(
                decision="MERGED_HEAD" if is_merged else "KEEP",
                merged_with=source_ids[1:] if is_merged else [],
                merge_score=group.merge_score,
                merge_reason=group.reason,
            )

            next_id = self._make_id(i + 2, [groups[i + 1].segments[0].segment_id]) if i + 1 < len(groups) else ""

            v_start = float(group.segments[0].video_start)
            v_end = float(group.segments[-1].video_end)
            v_span = max(0.0, v_end - v_start)
            audio_offset = max(
                0.0,
                float(getattr(head, "audio_offset", 0.0) or 0.0),
            )

            seg = TimelineSegment(
                id=tl_id,
                source_ids=source_ids,
                room_type=head.room_type,
                role=head.role,
                arc_stage=head.arc_stage,
                importance=max(s.importance for s in group.segments),
                source=SourceTiming(
                    video_start=v_start,
                    video_end=v_end,
                    video_duration=round(v_span, 2),
                ),
                narration=NarrationInfo(
                    text=narration_text,
                    tts_text=tts_text,
                    audio_path=audio_path,
                    audio_duration=dur_dec.audio_duration,
                    estimated_duration=sum(s.estimated_duration for s in group.segments),
                    emotion=head.voice_emotion or head.emotion,
                    delivery_speed=head.delivery_speed,
                ),
                visual_plan=vis_plan,
                duration_decision=dur_dec,
                transition=TransitionPlan(
                    to_segment_id=next_id,
                    type=trans_raw["type"],
                    duration=trans_raw["duration"],
                    reason=trans_raw["reason"],
                ),
                merge=merge_info,
                timeline_start=round(cursor, 2),
                timeline_end=round(cursor + dur_dec.editing_window, 2),
                audio_offset=round(audio_offset, 3),
                room_visible_end=round(
                    float(getattr(group.segments[-1], "room_visible_end", 0.0) or v_end),
                    3,
                ),
            )
            segments.append(seg)
            cursor += dur_dec.editing_window + trans_raw["duration"]

        if self.continuous_walkthrough:
            segments = self._seal_source_continuity(segments)
            # Rebuild timeline cursor after any window adjustments
            cursor = 0.0
            for seg in segments:
                window = float(seg.duration_decision.editing_window)
                t_dur = float(seg.transition.duration or 0)
                seg.timeline_start = round(cursor, 2)
                seg.timeline_end = round(cursor + window, 2)
                cursor += window + t_dur

        total_duration = round(cursor, 2)

        output = TimelineOutput(
            project_id=state.project_id,
            total_duration=total_duration,
            segment_count=len(segments),
            merge_count=merge_count,
            hero_segment_ids=hero_ids,
            segments=segments,
        )

        # Module 6: Validate
        output.validation = self.validator.validate(output, hero_ids)

        logger.info(
            "Timeline complete: %d segments | total=%.1fs | merges=%d | valid=%s | issues=%d",
            len(segments),
            total_duration,
            merge_count,
            output.validation.is_valid,
            len(output.validation.issues),
        )

        return self.write_state(state, output.model_dump(mode="json"))

    async def refine_with_audio(self, state: ProjectState) -> ProjectState:
        """Final pass: keep approved timeline structure, inject measured audio.

        Unlike run(), this does NOT re-merge. It updates each timeline segment's
        narration + editing_window from Voice Execution + canonical script.
        """
        timeline = state.timeline or {}
        script = state.script or {}
        voice = state.voice or {}
        segments = timeline.get("segments", [])
        if not segments:
            raise ValueError("refine_with_audio requires an existing timeline")

        script_by_id = {
            str(s.get("segment_id", "")).split("[", 1)[0]: s
            for s in script.get("narration_segments", [])
        }
        voice_by_id: dict[str, dict] = {}
        for ve in voice.get("segments", []) or []:
            sid = str(ve.get("script_id") or ve.get("segment_id") or "")
            if sid:
                voice_by_id[sid.split("[", 1)[0]] = ve

        AUDIO_TAIL_PAD = 0.40
        MIN_SLOWMO_SOURCE = 6.0
        # Below this playback speed the shot visibly drags — a 4s window view
        # held for 8s reads as padding. Shorten the line instead of the picture.
        MIN_PLAYBACK_SPEED = 0.70
        cursor = 0.0
        updated = []
        for seg in segments:
            seg = dict(seg)
            safe_id = str(seg.get("id", "")).split("[", 1)[0]
            narr = dict(seg.get("narration") or {})
            source = dict(seg.get("source") or {})
            dur_dec = dict(seg.get("duration_decision") or {})
            trans = dict(seg.get("transition") or {})

            sc = script_by_id.get(safe_id, {})
            ve = voice_by_id.get(safe_id, {})

            if sc.get("text"):
                narr["text"] = sc["text"]
            if ve.get("audio_path"):
                narr["audio_path"] = ve["audio_path"]
            audio_dur = float(ve.get("duration") or narr.get("audio_duration") or 0)
            audio_path = ve.get("audio_path") or narr.get("audio_path")
            if audio_path:
                try:
                    from pathlib import Path as _Path
                    from backend.tools.audio_utils import get_audio_duration

                    probed = get_audio_duration(_Path(str(audio_path)))
                    if probed > 0.05:
                        if audio_dur > 0.1 and probed > audio_dur * 1.4:
                            logger.warning(
                                "TTS meta duration %.2fs << file %.2fs for %s — using ffprobe",
                                audio_dur,
                                probed,
                                safe_id,
                            )
                        audio_dur = probed
                except Exception:
                    pass
            narr["audio_duration"] = audio_dur

            video_dur = float(source.get("video_duration") or 0)
            v_start = float(source.get("video_start") or 0)
            v_end = float(source.get("video_end") or 0)
            if v_end > v_start:
                video_dur = max(video_dur, v_end - v_start)
                source["video_duration"] = round(video_dur, 2)
                seg["source"] = source
            audio_offset = max(0.0, float(seg.get("audio_offset") or 0.0))

            occupied = audio_offset + audio_dur
            available_audio = max(0.0, video_dur - audio_offset - AUDIO_TAIL_PAD)
            window = video_dur
            if window <= 0:
                window = float(dur_dec.get("editing_window") or 0)

            if (
                audio_offset > 0.05
                and audio_dur > 0
                and audio_dur > available_audio + 0.35
            ):
                # Preserve "enter before speaking". The recorded line must be
                # shortened and re-synthesized; moving offset earlier recreates
                # hallway/bathroom and kitchen/bedroom trust breaks.
                dur_dec["strategy"] = "flag_rewrite"
                dur_dec["extension_factor"] = 1.0
                dur_dec["needs_script_rewrite"] = True
                dur_dec["target_audio_duration"] = round(available_audio, 2)
                window = video_dur
            elif occupied > video_dur + 0.5:
                factor = round(video_dur / occupied, 3) if occupied else 1.0
                if video_dur < MIN_SLOWMO_SOURCE:
                    dur_dec["strategy"] = "flag_rewrite"
                    dur_dec["extension_factor"] = 1.0
                    dur_dec["needs_script_rewrite"] = True
                    dur_dec["target_audio_duration"] = round(available_audio, 2)
                    window = video_dur
                else:
                    dur_dec["strategy"] = "slow_motion"
                    dur_dec["extension_factor"] = factor
                    dur_dec["needs_script_rewrite"] = factor < MIN_PLAYBACK_SPEED
                    dur_dec["target_audio_duration"] = round(available_audio, 2)
                    window = max(video_dur, occupied + AUDIO_TAIL_PAD)
            else:
                # The line now fits. Clear any stretch an earlier pass granted —
                # a stale factor here freezes a shot to cover audio that has
                # since been shortened and re-recorded.
                dur_dec["strategy"] = "trim_video"
                dur_dec["extension_factor"] = 1.0
                dur_dec["needs_script_rewrite"] = False
                dur_dec["target_audio_duration"] = round(available_audio, 2)
                window = video_dur
            dur_dec["audio_duration"] = audio_dur
            dur_dec["video_duration"] = video_dur
            dur_dec["delta"] = round(audio_dur - video_dur, 2)
            dur_dec["editing_window"] = round(window, 2)

            seg["narration"] = narr
            seg["duration_decision"] = dur_dec
            seg["timeline_start"] = round(cursor, 2)
            seg["timeline_end"] = round(cursor + window, 2)
            updated.append(seg)
            cursor += window + float(trans.get("duration") or 0)

        if self.continuous_walkthrough:
            # Convert to TimelineSegment-like seal via dicts
            for i in range(len(updated) - 1):
                cur = updated[i]
                nxt = updated[i + 1]
                cur_src = cur.setdefault("source", {})
                nxt_src = nxt.setdefault("source", {})
                cur_end = float(cur_src.get("video_end", 0) or 0)
                nxt_start = float(nxt_src.get("video_start", 0) or 0)
                if nxt_start > cur_end + 0.05:
                    cur_src["video_end"] = round(nxt_start, 2)
                    cur_src["video_duration"] = round(
                        float(cur_src["video_end"]) - float(cur_src.get("video_start", 0) or 0),
                        2,
                    )
                    dur = cur.setdefault("duration_decision", {})
                    dur["editing_window"] = max(
                        float(dur.get("editing_window") or 0),
                        float(cur_src["video_duration"]),
                    )
                    dur["video_duration"] = float(cur_src["video_duration"])
            # Rebuild cursor
            cursor = 0.0
            for seg in updated:
                window = float(seg.get("duration_decision", {}).get("editing_window") or 0)
                t_dur = float(seg.get("transition", {}).get("duration") or 0)
                seg["timeline_start"] = round(cursor, 2)
                seg["timeline_end"] = round(cursor + window, 2)
                cursor += window + t_dur

        out = dict(timeline)
        out["segments"] = updated
        out["segment_count"] = len(updated)
        out["total_duration"] = round(cursor, 2)
        out["refined_with_audio"] = True
        logger.info(
            "Timeline refine_with_audio: %d segments | total=%.1fs",
            len(updated), cursor,
        )
        return self.write_state(state, out)

    def extract_rewrite_requests(self, timeline_output: dict) -> list[dict]:
        """Extract rewrite requests from FLAG_REWRITE segments in a timeline output.

        Returns a list of dicts ready to pass to ScriptAgent.rewrite_for_timeline().
        """
        requests: list[dict] = []
        for seg in timeline_output.get("segments", []):
            dur_dec = seg.get("duration_decision", {})
            if dur_dec.get("strategy") != "flag_rewrite":
                continue
            requests.append({
                "timeline_segment_id": seg["id"],
                "source_ids": seg.get("source_ids", []),
                "audio_duration": dur_dec.get("audio_duration", 0.0),
                "video_duration": dur_dec.get("video_duration", 0.0),
                "target_audio_duration": dur_dec.get("target_audio_duration", 0.0),
                "delta": dur_dec.get("delta", 0.0),
                "role": seg.get("role", ""),
                "room_type": seg.get("room_type", ""),
            })
        return requests

    def _seal_source_continuity(
        self, segments: list[TimelineSegment]
    ) -> list[TimelineSegment]:
        """Close gaps between consecutive source ranges; keep full spans.

        Absorbs inter-segment gaps into the earlier segment so Rendering
        never drops walkthrough frames between rooms.
        """
        if len(segments) < 2:
            return segments

        for i in range(len(segments) - 1):
            cur = segments[i]
            nxt = segments[i + 1]
            gap = float(nxt.source.video_start) - float(cur.source.video_end)
            if gap <= 0.05:
                continue
            logger.info(
                "Sealing timeline gap %.2fs between %s and %s",
                gap,
                cur.id,
                nxt.id,
            )
            cur.source.video_end = float(nxt.source.video_start)
            cur.source.video_duration = round(
                cur.source.video_end - cur.source.video_start, 2
            )
            window = max(
                float(cur.duration_decision.editing_window),
                float(cur.source.video_duration),
            )
            cur.duration_decision.editing_window = round(window, 2)
            cur.duration_decision.video_duration = float(cur.source.video_duration)

        return segments

    def _make_id(self, idx: int, source_ids: list[str]) -> str:
        if len(source_ids) == 1:
            return f"tl_{idx:03d}"
        return f"tl_{idx:03d}[{'_'.join(source_ids)}]"


# Backward-compat alias
TimelineOptimizationAgent = TimelineAgent
