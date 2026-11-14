"""Cinematic Reasoner — LLM brain of the Editing Agent.

Understands Vision + Timeline + Script + selling points, then produces
director decisions. Never touches media or timestamps.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.editing.prompts import EDITING_DIRECTOR_SYSTEM, build_director_user_prompt
from backend.agents.script.utils import SCRIPT_LLM_MAX_TOKENS, safe_extract_json
from backend.schemas.editing_schema import DirectorDecision, FocusElement
from backend.services.llm.base import LLMMessage

logger = logging.getLogger(__name__)

EDITING_LLM_BATCH_SIZE = 5
_DECISION_LIST_KEYS = ("decisions", "items", "segments", "results")


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if "```json" in cleaned:
        parts = cleaned.split("```json", 1)
        if len(parts) > 1:
            cleaned = parts[1].split("```", 1)[0].strip()
    elif "```" in cleaned:
        parts = cleaned.split("```", 1)
        if len(parts) > 1:
            cleaned = parts[1].split("```", 1)[0].strip()
    return cleaned


def _as_decision_list(parsed: Any) -> list | None:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in _DECISION_LIST_KEYS:
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        if parsed.get("segment_id"):
            return [parsed]
    return None


def _repair_json_array(text: str) -> list | None:
    """Keep complete objects when the model truncates a JSON array."""
    start = text.find("[")
    if start < 0:
        return None
    chunk = text[start:]
    try:
        data = json.loads(chunk, strict=False)
        return data if isinstance(data, list) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    for i in range(len(chunk) - 1, -1, -1):
        if chunk[i] != "}":
            continue
        candidate = chunk[: i + 1].rstrip().rstrip(",") + "]"
        try:
            data = json.loads(candidate, strict=False)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(data, list):
            return data
    return None


def extract_decision_list(text: str | None) -> list | None:
    """Parse a director-decision JSON list from messy LLM text.

    Accepts a raw array, a single object, a wrapper dict, fenced markdown,
    leading prose, or a truncated array that still has complete objects.
    """
    if not text or not str(text).strip():
        return None
    raw = str(text)
    found = _as_decision_list(safe_extract_json(raw, fallback=None))
    if found is not None:
        return found
    stripped = _strip_fences(raw)
    if stripped != raw:
        found = _as_decision_list(safe_extract_json(stripped, fallback=None))
        if found is not None:
            return found
    return _repair_json_array(stripped)


class CinematicReasoner:
    """LLM-backed cinematic director.

    Rule fallback is used only when a reply is still unparseable after retry
    and a per-segment call, so export can finish. Valid LLM decisions are kept.
    """

    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    @property
    def llm_available(self) -> bool:
        return self.llm_provider is not None

    async def reason(
        self,
        tl_segments: list[dict],
        style: str,
        audience: str,
        vision_by_id: dict[str, dict] | None = None,
    ) -> dict[str, DirectorDecision]:
        if self.llm_provider is None:
            raise RuntimeError(
                "CinematicReasoner requires an LLM provider. "
                "Start the LLM server and pass OpenAIProvider — rule fallback is disabled."
            )

        vision_by_id = vision_by_id or {}
        payloads = [
            self._build_payload(seg, vision_by_id)
            for seg in tl_segments
        ]

        decisions: dict[str, DirectorDecision] = {}
        for i in range(0, len(payloads), EDITING_LLM_BATCH_SIZE):
            batch = payloads[i : i + EDITING_LLM_BATCH_SIZE]
            batch_decisions = await self._call_llm(batch, style, audience)
            decisions.update(batch_decisions)

        for payload in payloads:
            sid = payload["segment_id"]
            if sid not in decisions:
                logger.warning(
                    "CinematicReasoner missing decision for %s — using rule fallback",
                    sid,
                )
                decisions[sid] = self._rule_fallback(payload)
        return decisions

    async def _call_llm(
        self,
        batch: list[dict],
        style: str,
        audience: str,
    ) -> dict[str, DirectorDecision]:
        parsed = await self._generate_list(batch, style, audience, attempts=2)
        out = self._decisions_from_parsed(parsed, batch) if parsed is not None else {}

        missing = [p for p in batch if p["segment_id"] not in out]
        if missing and len(batch) > 1:
            # A 5-segment batch often truncates; one-by-one keeps LLM decisions.
            for payload in missing:
                one = await self._generate_list([payload], style, audience, attempts=1)
                out.update(self._decisions_from_parsed(one, [payload]))

        for payload in batch:
            sid = payload["segment_id"]
            if sid in out:
                continue
            logger.warning(
                "CinematicReasoner unusable LLM reply for %s — using rule fallback",
                sid,
            )
            out[sid] = self._rule_fallback(payload)
        return out

    async def _generate_list(
        self,
        batch: list[dict],
        style: str,
        audience: str,
        attempts: int,
    ) -> list | None:
        messages = [
            LLMMessage(role="system", content=EDITING_DIRECTOR_SYSTEM),
            LLMMessage(
                role="user",
                content=build_director_user_prompt(batch, style, audience),
            ),
        ]
        parsed: list | None = None
        for attempt in range(attempts):
            try:
                response = await self.llm_provider.generate(
                    messages,
                    temperature=0.4 if attempt == 0 else 0.15,
                    max_tokens=SCRIPT_LLM_MAX_TOKENS,
                )
                parsed = extract_decision_list(getattr(response, "content", None))
            except Exception as exc:
                logger.warning(
                    "CinematicReasoner LLM call failed (attempt %d/%d): %s",
                    attempt + 1,
                    attempts,
                    exc,
                )
                parsed = None
            if parsed is not None:
                return parsed
            logger.warning(
                "CinematicReasoner batch unusable (attempt %d/%d): response was not a JSON list",
                attempt + 1,
                attempts,
            )
        return None

    def _decisions_from_parsed(
        self,
        parsed: list | None,
        batch: list[dict],
    ) -> dict[str, DirectorDecision]:
        if not isinstance(parsed, list):
            return {}
        out: dict[str, DirectorDecision] = {}
        by_id = {p["segment_id"]: p for p in batch}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("segment_id", ""))
            if sid not in by_id:
                continue
            out[sid] = self._parse_decision(item)
        return out

    def _parse_decision(self, item: dict) -> DirectorDecision:
        focus_raw = item.get("focus_order") or []
        focus: list[FocusElement] = []
        for i, f in enumerate(focus_raw):
            if isinstance(f, dict):
                focus.append(FocusElement(
                    element=str(f.get("element", "")),
                    reason=str(f.get("reason", "")),
                    priority=int(f.get("priority", i + 1)),
                ))
            elif isinstance(f, str):
                focus.append(FocusElement(element=f, priority=i + 1))

        styles = item.get("recommended_style") or []
        if isinstance(styles, str):
            styles = [styles]

        return DirectorDecision(
            visual_goal=str(item.get("visual_goal", "")),
            focus_order=focus,
            recommended_style=[str(s) for s in styles],
            pacing_hint=str(item.get("pacing_hint", "")),
            transition_hint=str(item.get("transition_hint", "")),
            subtitle_hint=str(item.get("subtitle_hint", "")),
            reason=str(item.get("reason", "")),
        )

    def _build_payload(self, tl_seg: dict, vision_by_id: dict[str, dict]) -> dict:
        narr = tl_seg.get("narration", {})
        visual = tl_seg.get("visual_plan", {})
        source_ids = tl_seg.get("source_ids", [])
        vision_bits = []
        for sid in source_ids:
            if sid in vision_by_id:
                vision_bits.append(vision_by_id[sid])

        return {
            "segment_id": tl_seg.get("id", ""),
            "timeline": {
                "role": tl_seg.get("role", "SUPPORT"),
                "duration": float(tl_seg.get("source", {}).get("video_duration", 0)),
                "story_phase": visual.get("story_phase", ""),
                "arc_stage": tl_seg.get("arc_stage", ""),
                "importance": float(tl_seg.get("importance", 0.5)),
                "duration_strategy": tl_seg.get("duration_decision", {}).get("strategy", ""),
            },
            "vision": {
                "room": tl_seg.get("room_type", ""),
                "focus_elements": visual.get("focus_elements", []),
                "cinematic_intent": visual.get("cinematic_intent", ""),
                "source_vision": vision_bits[:2],
            },
            "script": {
                "text": narr.get("text", ""),
            },
            "transition_from_timeline": tl_seg.get("transition", {}),
        }

    def _rule_fallback(self, payload: dict) -> DirectorDecision:
        role = payload.get("timeline", {}).get("role", "SUPPORT")
        room = payload.get("vision", {}).get("room", "space")
        focus_els = payload.get("vision", {}).get("focus_elements", []) or [room]
        importance = float(payload.get("timeline", {}).get("importance", 0.5))

        if role == "HERO" or importance >= 0.85:
            styles = ["wide_shot", "slow_push", "premium_text"]
            pacing, sub = "slow", "premium"
            goal = f"emphasize {room} selling points"
        elif role == "TRANSITION":
            styles = ["wide_shot", "minimal_text"]
            pacing, sub = "fast", "minimal"
            goal = f"guide spatial flow through {room}"
        elif payload.get("timeline", {}).get("arc_stage") == "close":
            styles = ["wide_shot", "slow_push", "minimal_text"]
            pacing, sub = "slow", "minimal"
            goal = "emotional close"
        else:
            styles = ["wide_shot", "minimal_text"]
            pacing, sub = "medium", "minimal"
            goal = f"present {room} clearly"

        focus = [
            FocusElement(element=str(e), reason="timeline focus", priority=i + 1)
            for i, e in enumerate(focus_els[:3])
        ]
        return DirectorDecision(
            visual_goal=goal,
            focus_order=focus,
            recommended_style=styles,
            pacing_hint=pacing,
            transition_hint="",
            subtitle_hint=sub,
            reason="rule_fallback",
        )
