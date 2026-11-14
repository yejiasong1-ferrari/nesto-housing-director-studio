"""Module 3: Segment Reasoner.

DEPRECATED: Replaced by narrative/flow_builder.py + attention hierarchy.
Kept for backward compatibility only. Do not use in new code.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.planner.prompts import load_prompt, REASONING_PROMPT_PATH
from backend.agents.planner.utils import coerce_float, coerce_str_list, safe_extract_json, PLANNER_LLM_MAX_TOKENS
from backend.schemas.planning_schema import AttentionEntry, DirectorIntent, SegmentReasoning
from backend.schemas.vision_schema import VisionKnowledgeBase
from backend.services.llm.base import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)

HERO_THRESHOLD = 0.85
SUPPORT_THRESHOLD = 0.55


class SegmentReasoner:
    """Converts attention → cinematic meaning (role, focus, narration weight)."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def reason(
        self,
        intent: DirectorIntent,
        vkb: VisionKnowledgeBase,
        attention_map: list[AttentionEntry],
    ) -> list[SegmentReasoning]:
        """Produce segment reasoning for all segments."""
        attention_by_id = {a.segment_id: a for a in attention_map}
        llm_reasoning = await self._llm_reason(intent, vkb, attention_map)

        results: list[SegmentReasoning] = []
        for segment in vkb.segments:
            seg_id = segment.segment_id
            attention = attention_by_id.get(seg_id)
            score = attention.score if attention else 0.5

            llm_entry = llm_reasoning.get(seg_id, {})
            role = str(llm_entry.get("role", "")) or self._rule_role(score)
            focus = coerce_str_list(llm_entry.get("focus_points", []))
            if not focus:
                focus = self._rule_focus_points(segment, attention)

            narration_weight = coerce_float(
                llm_entry.get("narration_weight", self._rule_narration_weight(score)),
                default=self._rule_narration_weight(score),
            )

            results.append(
                SegmentReasoning(
                    segment_id=seg_id,
                    role=role,
                    focus_points=focus,
                    narration_weight=narration_weight,
                )
            )

        logger.info("Reasoned over %d segments", len(results))
        return results

    async def _llm_reason(
        self,
        intent: DirectorIntent,
        vkb: VisionKnowledgeBase,
        attention_map: list[AttentionEntry],
    ) -> dict[str, dict[str, Any]]:
        """LLM-assisted cinematic meaning extraction."""
        if self.llm_provider is None:
            return {}

        payload = []
        for seg in vkb.segments:
            att = next((a for a in attention_map if a.segment_id == seg.segment_id), None)
            payload.append({
                "segment_id": seg.segment_id,
                "room_type": seg.knowledge.room_type,
                "attention_score": att.score if att else 0.5,
                "selling_points": seg.knowledge.selling_points[:6],
                "lighting": seg.knowledge.lighting,
                "camera_motion": seg.knowledge.camera.motion,
            })

        prompt = load_prompt(
            REASONING_PROMPT_PATH,
            intent_json=json.dumps(intent.model_dump(), indent=2),
            segments_json=json.dumps(payload, indent=2),
        )

        try:
            response = await self.llm_provider.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.3,
                max_tokens=PLANNER_LLM_MAX_TOKENS,
            )
            if not (response.content or "").strip():
                logger.warning(
                    "Reasoning LLM empty response (finish=%s, tokens=%s)",
                    response.finish_reason,
                    response.usage,
                )
            data = safe_extract_json(response.content, fallback=[])
            return self._parse_llm_reasoning(data)
        except Exception as exc:
            logger.error("Segment reasoning LLM failed: %s", exc, exc_info=True)
            return {}

    def _parse_llm_reasoning(self, data: Any) -> dict[str, dict[str, Any]]:
        """Parse LLM reasoning response."""
        result: dict[str, dict[str, Any]] = {}

        items = data
        if isinstance(data, dict):
            items = data.get("segment_reasoning", data.get("segments", []))

        if not isinstance(items, list):
            return result

        for item in items:
            if isinstance(item, dict) and item.get("segment_id"):
                result[str(item["segment_id"])] = item

        return result

    def _rule_role(self, score: float) -> str:
        if score >= HERO_THRESHOLD:
            return "hero_segment"
        if score >= SUPPORT_THRESHOLD:
            return "support_segment"
        return "transition_segment"

    def _rule_narration_weight(self, score: float) -> float:
        return round(min(1.0, max(0.2, score)), 2)

    def _rule_focus_points(self, segment: Any, attention: AttentionEntry | None) -> list[str]:
        """Extract focus points from selling points and attention reasons."""
        points = segment.knowledge.selling_points[:3]

        if attention:
            for reason in attention.reason:
                if reason.endswith("_match"):
                    points.append(reason.replace("_match", "").replace("_", " "))

        if segment.knowledge.lighting.lower() in ("excellent", "good"):
            points.append("lighting")

        if segment.knowledge.camera.motion:
            points.append("camera_motion")

        return list(dict.fromkeys(points))[:5]
