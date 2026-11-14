"""CinematicReasoner must recover from unparseable LLM replies without dying."""

from __future__ import annotations

from typing import Any

import pytest

from backend.agents.editing.director.cinematic_reasoner import (
    CinematicReasoner,
    extract_decision_list,
)
from backend.services.llm.base import LLMMessage, LLMProvider, LLMResponse


def test_extract_decision_list_accepts_wrapped_dict() -> None:
    raw = '{"decisions": [{"segment_id": "tl_001", "visual_goal": "show room"}]}'
    parsed = extract_decision_list(raw)
    assert parsed is not None
    assert parsed[0]["segment_id"] == "tl_001"


def test_extract_decision_list_accepts_single_object() -> None:
    raw = '{"segment_id": "tl_002", "visual_goal": "hero kitchen"}'
    parsed = extract_decision_list(raw)
    assert parsed is not None
    assert parsed[0]["segment_id"] == "tl_002"


def test_extract_decision_list_repairs_truncated_array() -> None:
    raw = (
        '[{"segment_id": "tl_001", "visual_goal": "open"},'
        ' {"segment_id": "tl_002", "visual_goal": "hero", "reason": "cut off'
    )
    parsed = extract_decision_list(raw)
    assert parsed is not None
    assert [item["segment_id"] for item in parsed] == ["tl_001"]


def test_extract_decision_list_empty_is_none() -> None:
    assert extract_decision_list("") is None
    assert extract_decision_list(None) is None


class _EmptyLLM(LLMProvider):
    async def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        return LLMResponse(content="", model="mock", finish_reason="length")

    async def generate_structured(
        self, messages: list[LLMMessage], response_schema: dict[str, Any], **kwargs: Any,
    ) -> dict[str, Any]:
        return {}


class _BatchThenSingleLLM(LLMProvider):
    """First batch call is garbage; the per-segment retry returns valid JSON."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        content = messages[-1].content
        if self.calls <= 2:
            return LLMResponse(content="thinking...", model="mock", finish_reason="stop")
        sid = "tl_001" if "tl_001" in content else "tl_002"
        return LLMResponse(
            content=(
                f'[{{"segment_id": "{sid}", "visual_goal": "from-llm",'
                f' "recommended_style": ["slow_push"], "reason": "ok"}}]'
            ),
            model="mock",
            finish_reason="stop",
        )

    async def generate_structured(
        self, messages: list[LLMMessage], response_schema: dict[str, Any], **kwargs: Any,
    ) -> dict[str, Any]:
        return {}


def _seg(seg_id: str, role: str = "SUPPORT") -> dict:
    return {
        "id": seg_id,
        "source_ids": [seg_id],
        "room_type": "Kitchen",
        "role": role,
        "arc_stage": "explore",
        "importance": 0.9 if role == "HERO" else 0.5,
        "source": {"video_duration": 6.0},
        "narration": {"text": "Kitchen with an island."},
        "duration_decision": {"strategy": "trim_video"},
        "visual_plan": {"story_phase": "core_spaces", "focus_elements": ["island"]},
        "transition": {"type": "cut"},
    }


@pytest.mark.asyncio
async def test_reason_survives_empty_llm_with_rule_fallback() -> None:
    reasoner = CinematicReasoner(_EmptyLLM())
    decisions = await reasoner.reason([_seg("tl_001", "HERO")], "warm", "")
    assert "tl_001" in decisions
    assert decisions["tl_001"].reason == "rule_fallback"
    assert "slow_push" in decisions["tl_001"].recommended_style


@pytest.mark.asyncio
async def test_reason_retries_one_by_one_and_keeps_llm_decisions() -> None:
    llm = _BatchThenSingleLLM()
    reasoner = CinematicReasoner(llm)
    decisions = await reasoner.reason(
        [_seg("tl_001"), _seg("tl_002", "HERO")],
        "warm",
        "",
    )
    assert decisions["tl_001"].visual_goal == "from-llm"
    assert decisions["tl_002"].visual_goal == "from-llm"
    assert decisions["tl_001"].reason != "rule_fallback"
