"""Module 3: Narrative Flow Builder.

Roles come from attention hierarchy (HERO/SUPPORT/TRANSITION).
LLM refines emotion and narrative_function only.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.planner.attention.normalizer import ROLE_HERO, ROLE_TRANSITION
from backend.agents.planner.prompts import load_prompt, NARRATIVE_PROMPT_PATH
from backend.agents.planner.utils import coerce_float, safe_extract_json, PLANNER_LLM_MAX_TOKENS
from backend.schemas.planning_schema import AttentionEntry, DirectorIntent, NarrativeEntry
from backend.schemas.vision_schema import VisionKnowledgeBase
from backend.services.llm.base import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)

MAX_TRANSITION_NARRATION = 0.20


class NarrativeFlowBuilder:
    """Builds narrative flow aligned with attention hierarchy roles."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def build(
        self,
        intent: DirectorIntent,
        vkb: VisionKnowledgeBase,
        attention_map: list[AttentionEntry],
    ) -> list[NarrativeEntry]:
        """Produce narrative flow for all segments in video order."""
        attention_by_id = {a.segment_id: a for a in attention_map}
        llm_entries = await self._llm_narrative(intent, vkb, attention_map)

        segments = sorted(vkb.segments, key=lambda s: s.raw.start_time)
        results: list[NarrativeEntry] = []

        for segment in segments:
            seg_id = segment.segment_id
            llm_entry = llm_entries.get(seg_id, {})
            attention = attention_by_id.get(seg_id)
            role = attention.role if attention and attention.role else "SUPPORT"

            emotion = str(llm_entry.get("emotion", "")) or self._rule_emotion(role, intent)
            narrative_function = (
                str(llm_entry.get("narrative_function", ""))
                or self._rule_function(role, segment)
            )
            narration_weight = coerce_float(
                llm_entry.get("narration_weight", self._rule_narration_weight(role, attention)),
                default=self._rule_narration_weight(role, attention),
            )
            if role == ROLE_TRANSITION:
                narration_weight = min(narration_weight, MAX_TRANSITION_NARRATION)

            results.append(
                NarrativeEntry(
                    segment_id=seg_id,
                    role=role,
                    emotion=emotion,
                    narrative_function=narrative_function,
                    narration_weight=narration_weight,
                )
            )

        logger.info("Built narrative flow for %d segments (hierarchy-aligned)", len(results))
        return results

    async def _llm_narrative(
        self,
        intent: DirectorIntent,
        vkb: VisionKnowledgeBase,
        attention_map: list[AttentionEntry],
    ) -> dict[str, dict[str, Any]]:
        if self.llm_provider is None:
            return {}

        attention_by_id = {a.segment_id: a for a in attention_map}
        payload = []
        for seg in sorted(vkb.segments, key=lambda s: s.raw.start_time):
            att = attention_by_id.get(seg.segment_id)
            payload.append({
                "segment_id": seg.segment_id,
                "room_type": seg.knowledge.room_type,
                "role": att.role if att else "SUPPORT",
                "attention_score": att.score if att else 0.5,
                "selling_points": seg.knowledge.selling_points[:4],
                "start_time": seg.raw.start_time,
            })

        prompt = load_prompt(
            NARRATIVE_PROMPT_PATH,
            intent_json=json.dumps(intent.model_dump(), indent=2),
            segments_json=json.dumps(payload, indent=2),
        )

        try:
            response = await self.llm_provider.generate(
                messages=[LLMMessage(role="user", content=prompt),
                ],
                temperature=0.3,
                max_tokens=PLANNER_LLM_MAX_TOKENS,
            )
            data = safe_extract_json(response.content, fallback=[])
            return self._parse_llm_narrative(data)
        except Exception as exc:
            logger.error("Narrative LLM failed: %s", exc, exc_info=True)
            return {}

    def _parse_llm_narrative(self, data: Any) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        items = data
        if isinstance(data, dict):
            items = data.get("narrative_flow", data.get("segments", []))
        if not isinstance(items, list):
            return result
        for item in items:
            if isinstance(item, dict) and item.get("segment_id"):
                result[str(item["segment_id"])] = item
        return result

    def _rule_emotion(self, role: str, intent: DirectorIntent) -> str:
        tone = intent.emotional_tone.lower()
        if role == ROLE_HERO:
            if "luxury" in tone or "premium" in tone or "warm" in tone:
                return "premium"
            return "warmth"
        if role == ROLE_TRANSITION:
            return "neutral"
        if "premium" in tone or "luxury" in tone:
            return "premium"
        return "neutral"

    def _rule_function(self, role: str, segment: Any) -> str:
        room = segment.knowledge.room_type.lower()
        if role == ROLE_HERO:
            if "kitchen" in room:
                return "showcase_primary_living_feature"
            if "studio" in room or "living" in room:
                return "demonstrate_open_living_space"
            return "highlight_key_selling_space"
        if role == ROLE_TRANSITION:
            return "maintain_spatial_flow"
        return "support_narrative_continuity"

    def _rule_narration_weight(
        self,
        role: str,
        attention: AttentionEntry | None,
    ) -> float:
        role_weights = {
            "HERO": 0.90,
            "SUPPORT": 0.65,
            "TRANSITION": 0.15,
        }
        base = role_weights.get(role, 0.50)
        if attention and role != ROLE_TRANSITION:
            base = base * 0.6 + attention.score * 0.4
        return round(min(1.0, max(0.10, base)), 2)
