"""LLM Critic — attribution + fix decisions for detected issues.

Evaluators find problems; the critic decides root cause and owner.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.script.utils import SCRIPT_LLM_MAX_TOKENS, safe_extract_json
from backend.schemas.evaluation_schema import EvaluationIssue, FixAction, PriorityFix
from backend.services.llm.base import LLMMessage

logger = logging.getLogger(__name__)

CRITIC_SYSTEM = """You are the final-review director for a real estate walkthrough video.

You receive detected quality issues plus production context.
For each issue, decide:
- root_cause (short)
- owner: timeline_agent | editing_agent | script_agent
- action.type and action fields

Allowed action types:
- shift_video_start: value = seconds 0.5–2.0 only (never larger)
- extend_window: value = seconds to add to editing_window (0.3–2.0)
- compress_narration: value = max_words (int, 8–22)
- change_focus: target = focus element string
- add_emphasis: target = slow_zoom | zoom | ken_burns
- shorten_subtitle: value = max_chars
- adjust_bgm_volume: value = absolute volume_db (e.g. -25); owner = rendering_agent

Rules:
- Prefer timeline_agent for semantic_mismatch / temporal_shift / audio overflow
- Prefer editing_agent for wrong_visual_focus / hero_underemphasized / monotony
- Prefer script_agent for subtitle_overflow / wordy narration / foreign room words
- Prefer rendering_agent for bgm_overwhelms_narration / bgm_missing (adjust_bgm_volume only)
- Ignore encoding / resolution / fps notes. 1080×1920 portrait is the intended output.
- If evidence.suggested_shift exists, use it as shift_video_start value (clamped 0.5–2.0)
- NEVER set shift_video_start > 2.0
- Do NOT invent rooms or features
- Do NOT critique music style — only volume balance
- Return JSON array only, one object per issue (same order), with fields:
  segment_id, root_cause, owner, action {type, value, target}, problem
"""


class LLMCritic:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    @property
    def available(self) -> bool:
        return self.llm_provider is not None

    async def critique(
        self,
        issues: list[EvaluationIssue],
        context: dict[str, Any],
    ) -> list[PriorityFix]:
        if not issues:
            return []

        if self.llm_provider is None:
            return self._rule_critique(issues)

        payload = {
            "issues": [i.model_dump() for i in issues[:12]],
            "context_summary": context,
        }
        try:
            response = await self.llm_provider.generate(
                messages=[
                    LLMMessage(role="system", content=CRITIC_SYSTEM),
                    LLMMessage(
                        role="user",
                        content=json.dumps(payload, ensure_ascii=False, indent=2),
                    ),
                ],
                temperature=0.2,
                max_tokens=SCRIPT_LLM_MAX_TOKENS,
            )
            data = safe_extract_json(getattr(response, "content", "") or "", fallback=[])
        except Exception as exc:
            logger.warning("LLMCritic failed: %s — rule fallback", exc)
            return self._rule_critique(issues)

        if not isinstance(data, list) or not data:
            return self._rule_critique(issues)

        fixes: list[PriorityFix] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            issue = issues[i] if i < len(issues) else issues[-1]
            if _is_non_actionable_encoding(issue):
                continue
            action_raw = item.get("action") or {}
            if not isinstance(action_raw, dict):
                action_raw = {}
            owner = str(item.get("owner") or issue.suggested_target or "timeline_agent")
            if not owner.endswith("_agent"):
                owner = (
                    f"{owner}_agent"
                    if owner in ("timeline", "editing", "script", "rendering")
                    else owner
                )
            action_type = str(action_raw.get("type") or "")
            action_value = action_raw.get("value")
            # Clamp dangerous shifts from LLM
            if action_type == "shift_video_start":
                try:
                    action_value = max(0.5, min(2.0, float(action_value or 1.2)))
                except (TypeError, ValueError):
                    action_value = float(issue.evidence.get("suggested_shift") or 1.2)
                    action_value = max(0.5, min(2.0, action_value))
            if action_type == "adjust_bgm_volume":
                owner = "rendering_agent"
                try:
                    action_value = float(
                        action_value
                        if action_value is not None
                        else issue.evidence.get("suggested_bgm_volume_db", -25)
                    )
                except (TypeError, ValueError):
                    action_value = -20.0
                action_value = max(-40.0, min(-18.0, action_value))
            fixes.append(PriorityFix(
                id=f"fix_{i + 1:03d}",
                target_agent=owner,
                segment=str(item.get("segment_id") or issue.segment_id),
                problem=str(item.get("problem") or issue.description),
                action=FixAction(
                    type=action_type,
                    value=action_value,
                    target=str(action_raw.get("target") or ""),
                ),
                severity=issue.severity,
                root_cause=str(item.get("root_cause") or ""),
            ))
        return fixes or self._rule_critique(issues)

    def _rule_critique(self, issues: list[EvaluationIssue]) -> list[PriorityFix]:
        fixes: list[PriorityFix] = []
        for i, issue in enumerate(issues):
            action = FixAction()
            owner = "timeline_agent"
            if issue.type in ("semantic_mismatch", "temporal_shift", "timeline_drift", "timeline_gap", "audio_clipping_risk"):
                owner = "timeline_agent"
                if issue.type in ("semantic_mismatch", "temporal_shift"):
                    shift = issue.evidence.get("suggested_shift", 1.2)
                    try:
                        shift = float(shift)
                    except (TypeError, ValueError):
                        shift = 1.2
                    shift = max(0.5, min(2.0, shift))
                    # Script-owned foreign-room wording → compress instead
                    if issue.suggested_target == "script":
                        owner = "script_agent"
                        action = FixAction(type="compress_narration", value=16)
                    else:
                        action = FixAction(type="shift_video_start", value=shift)
                elif issue.type == "audio_clipping_risk":
                    overflow = float(issue.evidence.get("audio_duration", 0)) - float(
                        issue.evidence.get("editing_window", 0)
                    )
                    action = FixAction(type="extend_window", value=round(max(0.5, overflow + 0.4), 2))
                else:
                    action = FixAction(type="extend_window", value=0.5)
            elif issue.type in ("wrong_visual_focus", "hero_underemphasized", "cinematic_monotony"):
                owner = "editing_agent"
                if issue.type == "wrong_visual_focus":
                    focus = ""
                    if isinstance(issue.evidence.get("focus"), str):
                        focus = issue.evidence["focus"]
                    action = FixAction(type="change_focus", target=focus or "primary_selling_point")
                else:
                    action = FixAction(type="add_emphasis", target="slow_zoom")
            elif issue.type in ("subtitle_overflow", "subtitle_missing"):
                # Display-only by default — never rewrite spoken text without re-TTS.
                # compress_narration is reserved for true over-length vs audio window.
                owner = "editing_agent"
                action = FixAction(type="shorten_subtitle", value=48)
            elif issue.type in ("bgm_overwhelms_narration", "bgm_missing"):
                owner = "rendering_agent"
                suggested = issue.evidence.get("suggested_bgm_volume_db", -25)
                try:
                    suggested = float(suggested)
                except (TypeError, ValueError):
                    suggested = -20.0
                action = FixAction(
                    type="adjust_bgm_volume",
                    value=max(-40.0, min(-18.0, suggested)),
                )
            elif _is_non_actionable_encoding(issue):
                continue
            else:
                owner = f"{issue.suggested_target}_agent" if issue.suggested_target in (
                    "timeline", "editing", "script", "rendering"
                ) else "timeline_agent"
                action = FixAction(type="extend_window", value=0.5)

            # Map suggested_target override
            if issue.suggested_target == "editing":
                owner = "editing_agent"
            elif issue.suggested_target == "script":
                owner = "script_agent"
            elif issue.suggested_target == "timeline":
                owner = "timeline_agent"
            elif issue.suggested_target == "rendering":
                owner = "rendering_agent"

            fixes.append(PriorityFix(
                id=f"fix_{i + 1:03d}",
                target_agent=owner,
                segment=issue.segment_id,
                problem=issue.description,
                action=action,
                severity=issue.severity,
                root_cause=issue.type,
            ))
        return fixes


def _is_non_actionable_encoding(issue: EvaluationIssue) -> bool:
    """Resolution/fps nits cannot be fixed by a second MoviePy pass."""
    if issue.type != "encoding":
        return False
    desc = (issue.description or "").lower()
    if "missing" in desc or "status is" in desc:
        return False
    return True
