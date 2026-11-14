"""Module 4: Cinematic Reasoner.

Rule-based role strategies are primary.
LLM optionally fills cinematic_notes (camera_language, attention_guidance, emotion_engine).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.planner.cinematic.vocabulary import (
    build_role_cinematic,
    enrich_with_execution,
)
from backend.agents.planner.prompts import load_prompt, CINEMATIC_PROMPT_PATH
from backend.agents.planner.utils import safe_extract_json, PLANNER_LLM_MAX_TOKENS
from backend.schemas.planning_schema import (
    AttentionEntry,
    CinematicStrategy,
    DirectorIntent,
    NarrativeEntry,
)
from backend.schemas.vision_schema import VisionKnowledgeBase
from backend.services.llm.base import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)


class CinematicReasoner:
    """Produces role-based cinematic strategies per segment."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def reason(
        self,
        intent: DirectorIntent,
        vkb: VisionKnowledgeBase,
        attention_map: list[AttentionEntry],
        narrative_flow: list[NarrativeEntry],
    ) -> list[CinematicStrategy]:
        """Produce cinematic strategy for all segments."""
        attention_by_id = {a.segment_id: a for a in attention_map}
        llm_notes = await self._llm_cinematic_notes(intent, vkb, attention_map)

        results: list[CinematicStrategy] = []
        for segment in sorted(vkb.segments, key=lambda s: s.raw.start_time):
            seg_id = segment.segment_id
            attention = attention_by_id.get(seg_id)
            role = attention.role if attention and attention.role else "SUPPORT"

            strategy = build_role_cinematic(
                seg_id,
                role,
                intent,
                room_type=segment.knowledge.room_type,
                focus_points=segment.knowledge.selling_points[:3],
            )

            notes = llm_notes.get(seg_id, {})
            if notes:
                if notes.get("camera_language"):
                    strategy.camera_language = str(notes["camera_language"])
                if notes.get("attention_guidance"):
                    strategy.attention_guidance = str(notes["attention_guidance"])
                if notes.get("emotion_engine"):
                    strategy.emotion_engine = str(notes["emotion_engine"])

            results.append(enrich_with_execution(strategy))

        logger.info("Reasoned cinematic strategies for %d segments (role-based)", len(results))
        return results

    async def _llm_cinematic_notes(
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
                "importance": att.score if att else 0.5,
                "focus_points": seg.knowledge.selling_points[:3],
            })

        prompt = load_prompt(
            CINEMATIC_PROMPT_PATH,
            intent_json=json.dumps(intent.model_dump(), indent=2),
            segments_json=json.dumps(payload, indent=2),
        )

        try:
            response = await self.llm_provider.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.3,
                max_tokens=PLANNER_LLM_MAX_TOKENS,
            )
            data = safe_extract_json(response.content, fallback=[])
            return self._parse_llm_notes(data)
        except Exception as exc:
            logger.error("Cinematic LLM notes failed: %s", exc, exc_info=True)
            return {}

    def _parse_llm_notes(self, data: Any) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        items = data
        if isinstance(data, dict):
            items = data.get("cinematic_strategy", data.get("segments", []))
        if not isinstance(items, list):
            return result
        for item in items:
            if isinstance(item, dict) and item.get("segment_id"):
                result[str(item["segment_id"])] = {
                    k: item[k]
                    for k in ("camera_language", "attention_guidance", "emotion_engine")
                    if k in item
                }
        return result
