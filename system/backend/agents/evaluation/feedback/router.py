"""Feedback Router — apply single-round fixes (not an agent).

Dispatches PriorityFix actions to timeline / editing / script state dicts.
Does not re-enter Evaluation.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from backend.agents.evaluation.evaluators._helpers import safe_id
from backend.agents.script.utils import clause_aware_trim
from backend.schemas.evaluation_schema import PriorityFix

logger = logging.getLogger(__name__)


class FeedbackRouter:
    """Apply evaluation fixes once to production state artifacts."""

    def __init__(self, continuous_walkthrough: bool = True) -> None:
        self.continuous_walkthrough = continuous_walkthrough

    def apply(
        self,
        fixes: list[PriorityFix],
        *,
        timeline: dict[str, Any],
        editing: dict[str, Any],
        script: dict[str, Any],
        audio_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timeline = deepcopy(timeline)
        editing = deepcopy(editing)
        script = deepcopy(script)
        audio_config = deepcopy(audio_config) if audio_config else {
            "background_music": {
                "enabled": True,
                "path": "storage/audio/bgm/default_bgm.mp3",
                "volume_db": -18.0,
                "loop": True,
                "fade_in": 2.0,
                "fade_out": 3.0,
            }
        }
        applied: list[dict] = []
        needs_tts: list[str] = []

        for fix in fixes:
            agent = fix.target_agent
            try:
                # Global monotony fix (no segment) → diversify non-HERO cuts
                if (
                    not fix.segment
                    and fix.action.type == "add_emphasis"
                    and "monotony" in (fix.problem or "").lower()
                ):
                    self._diversify_effects(editing)
                    applied.append({"id": fix.id, "target": "editing_agent", "action": "diversify_effects"})
                    continue

                if agent == "timeline_agent":
                    changed = self._apply_timeline(fix, timeline, editing)
                elif agent == "editing_agent":
                    changed = self._apply_editing(fix, editing, timeline)
                elif agent == "script_agent":
                    changed, spoken = self._apply_script(fix, script, editing, timeline)
                    if spoken:
                        needs_tts.append(safe_id(fix.segment))
                elif agent == "rendering_agent":
                    changed = self._apply_rendering(fix, audio_config)
                else:
                    logger.warning("Unknown target_agent %s — skip %s", agent, fix.id)
                    continue
                if changed:
                    applied.append({"id": fix.id, "target": agent, "action": fix.action.type})
            except Exception as exc:
                logger.warning("Failed to apply %s: %s", fix.id, exc)

        # Only sync spoken narration when script text actually changed (compress).
        # shorten_subtitle must NOT rewrite spoken text / burn-in subtitles.
        if needs_tts:
            self._sync_narration_text(script, timeline, editing)

        return {
            "timeline": timeline,
            "editing": editing,
            "script": script,
            "audio_config": audio_config,
            "applied": applied,
            "needs_tts_segments": sorted(set(needs_tts)),
        }

    def _apply_rendering(self, fix: PriorityFix, audio_config: dict) -> bool:
        """Apply rendering-owned fixes (BGM volume only in V1)."""
        action = fix.action.type
        bgm = audio_config.setdefault("background_music", {})
        if not isinstance(bgm, dict):
            bgm = {}
            audio_config["background_music"] = bgm

        if action == "adjust_bgm_volume":
            try:
                vol = float(fix.action.value if fix.action.value is not None else -20)
            except (TypeError, ValueError):
                vol = -20.0
            vol = max(-40.0, min(-18.0, vol))
            current = bgm.get("volume_db")
            try:
                current_vol = float(current) if current is not None else None
            except (TypeError, ValueError):
                current_vol = None
            if current_vol is not None and abs(current_vol - vol) < 0.05 and bgm.get("enabled", True):
                logger.info("Fix %s: BGM already %.1f dB — no remix needed", fix.id, vol)
                return False
            bgm["volume_db"] = vol
            bgm["enabled"] = True
            logger.info("Fix %s: adjust_bgm_volume → %.1f dB", fix.id, vol)
            return True
        logger.warning("Unsupported rendering action %s — skip %s", action, fix.id)
        return False

    def _diversify_effects(self, editing: dict) -> None:
        for ed in editing.get("segments") or []:
            role = ed.get("role", "SUPPORT")
            if role == "HERO":
                continue
            vs = ed.setdefault("visual_strategy", {"focus": [], "operations": []})
            vs["operations"] = [{
                "type": "clean_cut",
                "target": "",
                "strength": 0.0,
                "parameters": {},
                "reason": "evaluation_fix:diversify_monotony",
            }]
            ed["visual_strategies"] = [
                {"type": "clean_cut", "parameters": {}, "reason": "diversify_monotony"}
            ]
        logger.info("Diversified non-HERO segments to clean_cut")

    def _find_tl(self, timeline: dict, segment: str) -> dict | None:
        sid = safe_id(segment)
        for seg in timeline.get("segments") or []:
            if safe_id(seg.get("id", "")) == sid:
                return seg
        return None

    def _find_edit(self, editing: dict, segment: str) -> dict | None:
        sid = safe_id(segment)
        for seg in editing.get("segments") or []:
            if safe_id(seg.get("segment_id", "")) == sid:
                return seg
        return None

    def _apply_timeline(self, fix: PriorityFix, timeline: dict, editing: dict) -> bool:
        seg = self._find_tl(timeline, fix.segment)
        if not seg:
            return False
        action = fix.action.type
        value = fix.action.value

        source = seg.setdefault("source", {})
        dur = seg.setdefault("duration_decision", {})
        narr = seg.setdefault("narration", {})

        if action == "shift_video_start":
            if self.continuous_walkthrough:
                # Shifting start deletes walkthrough head frames — extend instead
                logger.info(
                    "Fix %s: skip shift_video_start on %s (continuous_walkthrough)",
                    fix.id,
                    fix.segment,
                )
                return False
            # Cap shift — never destroy the clip
            delta = float(value or 1.0)
            delta = max(0.3, min(2.0, delta))
            # Prefer evidence-suggested shift when present in problem context
            v_start = float(source.get("video_start", 0) or 0)
            v_end = float(source.get("video_end", 0) or 0)
            span = max(0.5, v_end - v_start)
            # Keep at least 50% of original span
            max_delta = max(0.3, span * 0.5)
            delta = min(delta, max_delta)
            new_start = min(v_start + delta, v_end - 0.8)
            new_start = max(v_start, new_start)
            source["video_start"] = round(new_start, 2)
            source["video_duration"] = round(max(0.8, v_end - new_start), 2)
            ed = self._find_edit(editing, fix.segment)
            if ed:
                ed["video_start"] = source["video_start"]
                ed["video_duration"] = source["video_duration"]
            logger.info(
                "Fix %s: shift_video_start +%.2fs → %.2f on %s",
                fix.id, delta, new_start, fix.segment,
            )
            return True

        elif action == "extend_window":
            pad = float(value or 0.5)
            window = float(dur.get("editing_window") or source.get("video_duration") or 0)
            new_window = round(window + pad, 2)
            dur["editing_window"] = new_window
            # Prefer continuous slow-mo fill rather than inventing / freezing footage
            if float(narr.get("audio_duration") or 0) > float(source.get("video_duration") or 0):
                vdur = float(source.get("video_duration") or 0)
                adur = float(narr.get("audio_duration") or 0)
                dur["strategy"] = "slow_motion"
                if adur > 0:
                    dur["extension_factor"] = round(vdur / adur, 3)
            ed = self._find_edit(editing, fix.segment)
            if ed:
                ed["editing_window"] = new_window
            logger.info("Fix %s: extend_window → %.2fs on %s", fix.id, new_window, fix.segment)
            return True

        elif action == "shift_audio":
            # Represent as delaying visual start so audio lands on correct room
            delta = float(value or 1.0)
            return self._apply_timeline(
                PriorityFix(
                    id=fix.id,
                    target_agent="timeline_agent",
                    segment=fix.segment,
                    problem=fix.problem,
                    action=fix.action.model_copy(update={"type": "shift_video_start", "value": delta}),
                ),
                timeline,
                editing,
            )
        return False

    def _apply_script(
        self,
        fix: PriorityFix,
        script: dict,
        editing: dict,
        timeline: dict,
    ) -> tuple[bool, bool]:
        """Apply script-targeted fix.

        Returns (state_changed, needs_tts). shorten_subtitle is display-only.
        """
        sid = safe_id(fix.segment)
        action = fix.action.type

        # Display-only: wrap/size — keep audio and burn-in text identical
        if action == "shorten_subtitle":
            ed = self._find_edit(editing, sid)
            if ed is not None:
                sub = ed.setdefault("subtitle", {})
                if isinstance(sub, dict):
                    # value may be char budget from critic
                    max_chars = int(fix.action.value or 52)
                    if max_chars > 80:
                        max_chars = 52
                    sub["enabled"] = True
                    sub["max_chars_per_line"] = max(28, min(52, max_chars))
                    logger.info(
                        "Fix %s: shorten_subtitle display wrap=%d on %s (spoken text unchanged)",
                        fix.id, sub["max_chars_per_line"], sid,
                    )
                    return True, False
            return False, False

        if action == "compress_narration":
            max_words = int(fix.action.value or 18)
            if max_words > 40:
                max_words = max(10, max_words // 6)
            for ns in script.get("narration_segments") or []:
                if safe_id(ns.get("segment_id", "")) != sid:
                    continue
                old = ns.get("text", "")
                new = clause_aware_trim(old, max_words)
                if new.strip() == old.strip():
                    return False, False
                ns["text"] = new
                logger.info(
                    "Fix %s: compress_narration %s (%dw→%dw) — requires re-TTS",
                    fix.id, sid, len(old.split()), len(new.split()),
                )
                return True, True
            return False, False

        return False, False

    def _apply_editing(self, fix: PriorityFix, editing: dict, timeline: dict) -> bool:
        ed = self._find_edit(editing, fix.segment)
        if not ed:
            return False

        action = fix.action.type
        if action == "add_emphasis":
            # Diversify monotony: only emphasize HERO; SUPPORT/TRANSITION → clean_cut
            role = ed.get("role", "SUPPORT")
            if role != "HERO" and "monotony" in (fix.problem or "").lower():
                vs = ed.setdefault("visual_strategy", {"focus": [], "operations": []})
                vs["operations"] = [{
                    "type": "clean_cut",
                    "target": "",
                    "strength": 0.0,
                    "parameters": {},
                    "reason": f"evaluation_fix:{fix.id}:diversify",
                }]
                ed["visual_strategies"] = [{"type": "clean_cut", "parameters": {}, "reason": fix.id}]
                logger.info("Fix %s: diversify → clean_cut on %s", fix.id, fix.segment)
                return True
            target_fx = str(fix.action.target or "slow_zoom")
            focus = (ed.get("visual_strategy") or {}).get("focus") or []
            primary = focus[0] if focus else ed.get("room_type", "")
            op = {
                "type": target_fx if target_fx in ("slow_zoom", "zoom", "ken_burns") else "slow_zoom",
                "target": primary,
                "strength": 0.7 if role == "HERO" else 0.5,
                "parameters": {
                    "zoom_start": 1.0,
                    "zoom_end": 1.10 if role == "HERO" else 1.06,
                    "editing_window": ed.get("editing_window", 0),
                },
                "reason": f"evaluation_fix:{fix.id}",
            }
            vs = ed.setdefault("visual_strategy", {"focus": focus, "operations": []})
            vs["operations"] = [op]
            ed["visual_strategies"] = [{
                "type": op["type"],
                "parameters": op["parameters"],
                "reason": op["reason"],
            }]
            logger.info("Fix %s: add_emphasis %s on %s", fix.id, op["type"], fix.segment)
            return True

        elif action == "change_focus":
            target = str(fix.action.target or "").strip()
            if not target:
                return False
            vs = ed.setdefault("visual_strategy", {"focus": [], "operations": []})
            focus = list(vs.get("focus") or [])
            if target in focus:
                focus.remove(target)
            focus.insert(0, target)
            vs["focus"] = focus
            ops = vs.get("operations") or []
            if ops:
                ops[0]["target"] = target
                ops[0].setdefault("parameters", {})["target"] = target
            else:
                vs["operations"] = [{
                    "type": "slow_zoom",
                    "target": target,
                    "strength": 0.7,
                    "parameters": {"zoom_start": 1.0, "zoom_end": 1.10, "target": target},
                    "reason": f"evaluation_fix:{fix.id}",
                }]
            ed["visual_strategies"] = [{
                "type": (vs["operations"][0]["type"]),
                "parameters": vs["operations"][0].get("parameters", {}),
                "reason": f"evaluation_fix:{fix.id}",
            }]
            logger.info("Fix %s: change_focus → %s on %s", fix.id, target, fix.segment)
            return True

        elif action == "shorten_subtitle":
            sub = ed.setdefault("subtitle", {})
            if isinstance(sub, dict):
                sub["enabled"] = True
                sub["max_chars_per_line"] = int(fix.action.value or 48)
                return True
        return False

    def _sync_narration_text(self, script: dict, timeline: dict, editing: dict) -> None:
        by_id = {
            safe_id(s.get("segment_id", "")): s.get("text", "")
            for s in (script.get("narration_segments") or [])
        }
        for tl in timeline.get("segments") or []:
            sid = safe_id(tl.get("id", ""))
            if sid in by_id and by_id[sid]:
                tl.setdefault("narration", {})["text"] = by_id[sid]
        for ed in editing.get("segments") or []:
            sid = safe_id(ed.get("segment_id", ""))
            if sid in by_id and by_id[sid]:
                ed["narration_text"] = by_id[sid]
