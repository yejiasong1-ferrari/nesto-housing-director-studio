"""Audio-Visual Alignment Evaluator — 40% weight.

Checks temporal, semantic, and attention alignment between
narration / vision / editing.
"""

from __future__ import annotations

from typing import Any

from backend.agents.evaluation.evaluators._helpers import (
    ROOM_COMPAT,
    clamp_score,
    normalize_room,
    room_keywords_in_text,
    safe_id,
    vision_room_at_time,
)
from backend.schemas.evaluation_schema import EvaluationIssue

TEMPORAL_TOLERANCE = 0.6
AUDIO_OVERFLOW_TOLERANCE = 0.35


class AudioVisualEvaluator:
    weight = 0.40

    def evaluate(
        self,
        timeline: dict[str, Any],
        script: dict[str, Any],
        editing: dict[str, Any],
        vision: dict[str, Any],
        planning: dict[str, Any],
        voice: dict[str, Any] | None = None,
    ) -> tuple[float, list[EvaluationIssue]]:
        issues: list[EvaluationIssue] = []
        tl_segs = timeline.get("segments", []) or []
        script_by = {
            safe_id(s.get("segment_id", "")): s
            for s in (script.get("narration_segments") or [])
        }
        edit_by = {
            safe_id(s.get("segment_id", "")): s
            for s in (editing.get("segments") or [])
        }
        voice_by = {}
        for ve in (voice or {}).get("segments", []) or []:
            voice_by[safe_id(str(ve.get("script_id") or ve.get("segment_id") or ""))] = ve

        hero_source_ids = set(planning.get("hierarchy", {}).get("hero_segments", []) or [])

        penalties = 0.0

        for tl in tl_segs:
            sid = safe_id(tl.get("id", ""))
            source = tl.get("source", {})
            narr = tl.get("narration", {})
            visual = tl.get("visual_plan", {})
            v_start = float(source.get("video_start", 0) or 0)
            v_end = float(source.get("video_end", 0) or 0)
            v_dur = float(source.get("video_duration", v_end - v_start) or 0)
            window = float(tl.get("duration_decision", {}).get("editing_window") or v_dur)
            audio_dur = float(narr.get("audio_duration") or 0)
            if audio_dur <= 0 and sid in voice_by:
                audio_dur = float(voice_by[sid].get("duration") or 0)

            text = (
                narr.get("text")
                or script_by.get(sid, {}).get("text")
                or ""
            )
            room = tl.get("room_type", "")
            room_norm = normalize_room(room)

            # --- 1.1 Temporal: audio longer than visual window ---
            if audio_dur > 0 and audio_dur > window + AUDIO_OVERFLOW_TOLERANCE:
                overflow = round(audio_dur - window, 2)
                issues.append(EvaluationIssue(
                    type="audio_clipping_risk",
                    segment_id=sid,
                    severity="high" if overflow > 1.0 else "medium",
                    description=(
                        f"Narration ({audio_dur:.2f}s) exceeds editing window "
                        f"({window:.2f}s) by {overflow:.2f}s — risk of cutoff"
                    ),
                    evidence={"audio_duration": audio_dur, "editing_window": window},
                    suggested_target="timeline",
                ))
                penalties += 12 if overflow > 1.0 else 7

            text_rooms = room_keywords_in_text(text)

            # --- 1.2 Semantic: text rooms vs declared room ---
            foreign = text_rooms - {room_norm, "unknown"}
            allowed = ROOM_COMPAT.get(room_norm, set())
            foreign = foreign - allowed
            if foreign:
                issues.append(EvaluationIssue(
                    type="semantic_mismatch",
                    segment_id=sid,
                    severity="medium",
                    description=(
                        f"Narration mentions {sorted(foreign)} while "
                        f"segment room is '{room}'"
                    ),
                    evidence={"text": text[:120], "room": room},
                    suggested_target="script",
                ))
                penalties += 8

            # --- AV mismatch: narration room vs early frames ---
            # Only flag when early vision is a DIFFERENT room (true misalignment),
            # not merely because the clip starts at a room boundary.
            if text and room_norm and room_norm in text_rooms:
                early_vision = vision_room_at_time(vision, v_start + 0.35)
                early_norm = normalize_room(early_vision)
                if early_norm and early_norm != room_norm:
                    # Find when target room starts
                    room_start = None
                    for vseg in vision.get("segments", []) or []:
                        raw = vseg.get("raw", {})
                        kn = vseg.get("knowledge", {})
                        r = normalize_room(raw.get("room_type") or kn.get("room_type") or "")
                        if r == room_norm:
                            rs = float(raw.get("start_time", 0) or 0)
                            if rs >= v_start - 0.05:
                                room_start = rs if room_start is None else min(room_start, rs)
                    offset = 1.2
                    if room_start is not None and room_start > v_start:
                        offset = round(min(2.0, max(0.5, room_start - v_start + 0.4)), 2)
                    issues.append(EvaluationIssue(
                        type="semantic_mismatch",
                        segment_id=sid,
                        severity="high",
                        description=(
                            f"{room} narration starts while frames still show "
                            f"'{early_vision}'"
                        ),
                        evidence={
                            "timeline_room": room,
                            "early_vision": early_vision,
                            "video_start": v_start,
                            "suggested_shift": offset,
                            "text": text[:100],
                        },
                        suggested_target="timeline",
                    ))
                    penalties += 15

            # --- 1.3 Attention: HERO focus vs editing ops ---
            source_ids = set(tl.get("source_ids") or [])
            is_hero = tl.get("role") == "HERO" or bool(source_ids & hero_source_ids)
            focus = visual.get("focus_elements") or []
            edit_seg = edit_by.get(sid, {})
            ops = (
                edit_seg.get("visual_strategy", {}).get("operations")
                or edit_seg.get("visual_strategies")
                or []
            )
            op_types = [str(o.get("type", "")).lower() for o in ops]
            op_targets = " ".join(
                str(o.get("target", "") or o.get("parameters", {}).get("target", ""))
                for o in ops
            ).lower()

            if is_hero:
                has_emphasis = any(
                    t in ("slow_zoom", "zoom", "ken_burns", "slow_motion")
                    for t in op_types
                )
                if not has_emphasis or all(t in ("clean_cut", "") for t in op_types):
                    issues.append(EvaluationIssue(
                        type="hero_underemphasized",
                        segment_id=sid,
                        severity="medium",
                        description=f"HERO segment '{sid}' lacks visual emphasis",
                        evidence={"ops": op_types, "focus": focus[:2]},
                        suggested_target="editing",
                    ))
                    penalties += 10
                elif focus:
                    primary = str(focus[0]).lower()
                    # wrong focus if target mentions something unrelated to primary keywords
                    primary_tokens = {w for w in primary.replace("/", " ").split() if len(w) > 3}
                    if op_targets and primary_tokens and not (primary_tokens & set(op_targets.split())):
                        # Only flag if op target is clearly a different object family
                        if any(bad in op_targets for bad in ("cabinet", "door", "railing")) and \
                           any(good in primary for good in ("island", "window", "light", "bed", "sofa")):
                            issues.append(EvaluationIssue(
                                type="wrong_visual_focus",
                                segment_id=sid,
                                severity="medium",
                                description=(
                                    f"Editing emphasizes '{op_targets[:40]}' but "
                                    f"hero focus is '{focus[0]}'"
                                ),
                                evidence={"focus": focus[0], "op_targets": op_targets[:80]},
                                suggested_target="editing",
                            ))
                            penalties += 10

            # Gap between previous segment end and this start (source holes)
            # handled lightly — large source gaps with kitchen narration early
            # are covered by semantic check above.

        score = clamp_score(100.0 - penalties)
        return score, issues
