"""Module 1: Intent Interpreter.

Converts natural language user prompt into structured director intent.
This is the strongest LLM usage area in the Planner Agent.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.planner.prompts import load_prompt, INTENT_PROMPT_PATH
from backend.agents.planner.utils import safe_extract_json, PLANNER_INTENT_MAX_TOKENS
from backend.schemas.planning_schema import DirectorIntent, IntentConstraints, IntentGraph
from backend.services.llm.base import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)

# Default when prompt is empty/vague: cover space, facilities, and light
FALLBACK_INTENT = DirectorIntent(
    goal="real_estate_marketing",
    target_audience="general_buyer",
    intent_tags=[
        "showcase_property",
        "highlight_spaciousness",
        "highlight_facilities",
        "highlight_natural_light",
        "introduce_each_room",
    ],
    emotional_tone="professional_warm",
    intent_graph=IntentGraph(
        primary="space + facilities + natural_light",
        secondary="layout_and_flow",
        emotional_target="clear_livable_home",
        avoid=["empty_mood_adjectives", "commercial_tone"],
    ),
    constraints=IntentConstraints(preserve_video_order=True),
)


class IntentInterpreter:
    """Parses user prompt into structured director intent via LLM."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def interpret(
        self,
        user_prompt: str,
        property_metadata: dict[str, Any] | None = None,
    ) -> DirectorIntent:
        """Convert user prompt to structured DirectorIntent."""
        from backend.workflows.user_intent import is_vague_prompt

        if not user_prompt.strip() or is_vague_prompt(user_prompt):
            logger.info(
                "Empty/vague user prompt — using default space/facilities/light intent"
            )
            return FALLBACK_INTENT

        if self.llm_provider is None:
            return self._rule_based_intent(user_prompt)

        prompt = load_prompt(
            INTENT_PROMPT_PATH,
            user_prompt=user_prompt,
            property_metadata=json.dumps(property_metadata or {}, indent=2),
        )

        try:
            response = await self.llm_provider.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.3,
                max_tokens=PLANNER_INTENT_MAX_TOKENS,
            )
            data = safe_extract_json(response.content, fallback={})
            return self._parse_intent(data)
        except Exception as exc:
            logger.error("Intent interpretation failed: %s", exc, exc_info=True)
            return self._rule_based_intent(user_prompt)

    def _parse_intent(self, data: dict[str, Any]) -> DirectorIntent:
        """Parse LLM JSON into DirectorIntent."""
        if not isinstance(data, dict):
            return FALLBACK_INTENT

        constraints_data = data.get("constraints", {})
        if not isinstance(constraints_data, dict):
            constraints_data = {}

        tags = data.get("intent_tags", [])
        if not isinstance(tags, list):
            tags = [str(tags)] if tags else []

        graph_data = data.get("intent_graph", {})
        if not isinstance(graph_data, dict):
            graph_data = {}

        avoid = graph_data.get("avoid", [])
        if not isinstance(avoid, list):
            avoid = [str(avoid)] if avoid else []

        return DirectorIntent(
            goal=str(data.get("goal", "real_estate_marketing")),
            target_audience=str(data.get("target_audience", "")),
            intent_tags=[str(t) for t in tags],
            emotional_tone=str(data.get("emotional_tone", "")),
            intent_graph=IntentGraph(
                primary=str(graph_data.get("primary", "")),
                secondary=str(graph_data.get("secondary", "")),
                emotional_target=str(graph_data.get("emotional_target", "")),
                avoid=[str(a) for a in avoid],
            ),
            constraints=IntentConstraints(
                preserve_video_order=bool(
                    constraints_data.get("preserve_video_order", True)
                ),
            ),
        )

    def _rule_based_intent(self, user_prompt: str) -> DirectorIntent:
        """Fallback intent parsing without LLM."""
        prompt_lower = user_prompt.lower()
        tags: list[str] = ["showcase_property"]
        avoid: list[str] = []

        keyword_map = {
            "kitchen": "highlight_kitchen",
            "厨房": "highlight_kitchen",
            "living": "highlight_living_room",
            "客厅": "highlight_living_room",
            "bedroom": "highlight_bedroom",
            "卧室": "highlight_bedroom",
            "bathroom": "highlight_bathroom",
            "浴室": "highlight_bathroom",
            "卫生间": "highlight_bathroom",
            "light": "highlight_natural_light",
            "采光": "highlight_natural_light",
            "光线": "highlight_natural_light",
            "space": "highlight_spaciousness",
            "空间": "highlight_spaciousness",
            "facility": "highlight_facilities",
            "设施": "highlight_facilities",
            "家具": "highlight_facilities",
            "家电": "highlight_facilities",
            "介绍": "introduce_each_room",
            "luxury": "premium_feel",
            "高级": "premium_feel",
            "豪华": "premium_feel",
            "modern": "modern_style",
            "现代": "modern_style",
            "family": "family_friendly",
            "家庭": "family_friendly",
            "couple": "young_couple",
            "情侣": "young_couple",
            "warm": "warm_inviting",
            "温馨": "warm_inviting",
        }
        for keyword, tag in keyword_map.items():
            if keyword in prompt_lower or keyword in user_prompt:
                tags.append(tag)

        if "commercial" in prompt_lower or "商业化" in user_prompt:
            avoid.append("commercial_tone")

        primary_parts: list[str] = []
        if any(t in tags for t in ("highlight_kitchen",)):
            primary_parts.append("kitchen")
        if any(t in tags for t in ("highlight_living_room",)):
            primary_parts.append("living_room")
        if any(t in tags for t in ("highlight_natural_light",)):
            primary_parts.append("natural_light")
        if any(t in tags for t in ("highlight_spaciousness",)):
            primary_parts.append("spaciousness")
        primary = " + ".join(primary_parts) if primary_parts else "property_showcase"

        tone = "professional_warm"
        if "高级" in user_prompt or "luxury" in prompt_lower or "premium" in prompt_lower:
            tone = "warm_modern_luxury"
        elif "温馨" in user_prompt or "cozy" in prompt_lower or "warm" in prompt_lower:
            tone = "warm_inviting"

        audience = "general_buyer"
        if "family" in prompt_lower or "家庭" in user_prompt:
            audience = "young_family"
        elif "couple" in prompt_lower or "情侣" in user_prompt:
            audience = "young_couple"

        return DirectorIntent(
            goal="real_estate_marketing",
            target_audience=audience,
            intent_tags=list(dict.fromkeys(tags)),
            emotional_tone=tone,
            intent_graph=IntentGraph(
                primary=primary,
                secondary="spatial_flow",
                emotional_target="warm_secure_home" if audience == "young_family" else tone,
                avoid=avoid,
            ),
            constraints=IntentConstraints(preserve_video_order=True),
        )
