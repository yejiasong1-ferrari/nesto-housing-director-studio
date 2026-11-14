"""Tests for the redesigned Editing Strategy Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.agents.editing.agent import EditingAgent, EditingStrategyAgent
from backend.agents.editing.enrichment import enrich_timeline_narration
from backend.agents.editing.planners.pacing_strategy import PacingStrategyPlanner
from backend.agents.editing.planners.visual_strategy import VisualStrategyPlanner
from backend.agents.editing.validators.editing_constraint import EditingConstraintValidator
from backend.schemas.editing_schema import (
    DirectorDecision,
    EditingPlan,
    EditingSegmentPlan,
    FocusElement,
    VisualOperation,
    VisualStrategyBlock,
)
from backend.services.llm.base import LLMMessage, LLMProvider, LLMResponse
from backend.state.project_state import ProjectState


class _MockEditingLLM(LLMProvider):
    """Returns director decisions for every segment_id in the prompt."""

    async def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        import re
        content = messages[-1].content
        ids = re.findall(r'"segment_id":\s*"(tl_\d+|seg_\d+|[^"]+)"', content)
        # Prefer timeline-style ids from payload
        if not ids:
            ids = re.findall(r'"segment_id":\s*"([^"]+)"', content)
        items = []
        for sid in ids:
            items.append({
                "segment_id": sid,
                "visual_goal": "present space",
                "focus_order": [{"element": "primary feature", "priority": 1}],
                "recommended_style": ["slow_push"] if "002" in sid or "HERO" in content else ["wide_shot"],
                "pacing_hint": "slow" if "002" in sid else "medium",
                "transition_hint": "cut",
                "subtitle_hint": "minimal",
                "reason": "mock",
            })
        # Ensure unique
        seen = set()
        uniq = []
        for it in items:
            if it["segment_id"] not in seen:
                seen.add(it["segment_id"])
                uniq.append(it)
        return LLMResponse(content=json.dumps(uniq), model="mock", finish_reason="stop")

    async def generate_structured(
        self, messages: list[LLMMessage], response_schema: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return {}


_MOCK_LLM = _MockEditingLLM()


def _tl_seg(
    seg_id,
    role,
    arc,
    importance,
    dur_strategy="trim_video",
    story_phase="core_spaces",
    video_dur=6.0,
    ext_factor=1.0,
    editing_window=6.0,
    text="The kitchen features a marble island.",
):
    return {
        "id": seg_id,
        "source_ids": [seg_id],
        "room_type": "Kitchen",
        "role": role,
        "arc_stage": arc,
        "importance": importance,
        "source": {"video_start": 0.0, "video_end": video_dur, "video_duration": video_dur},
        "narration": {"text": text, "audio_path": "", "audio_duration": 4.0},
        "duration_decision": {
            "strategy": dur_strategy,
            "editing_window": editing_window,
            "extension_factor": ext_factor,
        },
        "visual_plan": {"story_phase": story_phase, "focus_elements": ["marble island"]},
        "transition": {"type": "cut", "duration": 0.0},
    }


@pytest.fixture
def full_timeline() -> dict:
    return {
        "segments": [
            _tl_seg("tl_001", "TRANSITION", "hook", 0.3, "trim_video", "opening_hook"),
            _tl_seg(
                "tl_002", "HERO", "highlight", 0.95, "slow_motion",
                "emotional_center", ext_factor=0.8, editing_window=7.5,
            ),
            _tl_seg("tl_003", "SUPPORT", "explore", 0.55, "trim_video", "core_spaces"),
        ]
    }


@pytest.fixture
def planning():
    return {"intent": {"emotional_tone": "warm_modern_luxury", "target_audience": "young_family"}}


@pytest.fixture
def state(full_timeline, planning) -> ProjectState:
    return ProjectState(project_id="test-001", timeline=full_timeline, planning=planning)


def test_alias_compat() -> None:
    assert EditingStrategyAgent is EditingAgent


@pytest.mark.asyncio
async def test_editing_agent_requires_llm(state: ProjectState) -> None:
    with pytest.raises(RuntimeError, match="requires an LLM"):
        await EditingAgent(llm_provider=None).run(state)


@pytest.mark.asyncio
async def test_editing_agent_run_with_llm(state: ProjectState) -> None:
    result = await EditingAgent(llm_provider=_MOCK_LLM).run(state)
    assert result.editing is not None
    assert result.editing.get("agent_name") == "editing"
    plan = EditingPlan.model_validate(result.editing)
    assert len(plan.segments) == 3
    assert plan.llm_used is True


@pytest.mark.asyncio
async def test_hero_gets_duration_driven_slow_motion(state: ProjectState) -> None:
    result = await EditingAgent(llm_provider=_MOCK_LLM).run(state)
    plan = EditingPlan.model_validate(result.editing)
    hero = next(s for s in plan.segments if s.role == "HERO")
    # duration strategy slow_motion from timeline still drives visual planner
    assert hero.primary_strategy().type in ("slow_motion", "slow_zoom", "zoom", "ken_burns")


@pytest.mark.asyncio
async def test_hook_gets_pacing_profile(state: ProjectState) -> None:
    result = await EditingAgent(llm_provider=_MOCK_LLM).run(state)
    plan = EditingPlan.model_validate(result.editing)
    hook = plan.segments[0]
    assert hook.pacing.style in ("cinematic", "brisk", "normal", "fade_out")


@pytest.mark.asyncio
async def test_subtitles_enabled_for_segments_with_text(state: ProjectState) -> None:
    result = await EditingAgent(llm_provider=_MOCK_LLM).run(state)
    plan = EditingPlan.model_validate(result.editing)
    for seg in plan.segments:
        if seg.narration_text.strip():
            assert seg.subtitle.enabled


@pytest.mark.asyncio
async def test_does_not_mutate_timestamps(state: ProjectState) -> None:
    before = {
        s["id"]: (s["source"]["video_start"], s["source"]["video_end"])
        for s in state.timeline["segments"]
    }
    result = await EditingAgent(llm_provider=_MOCK_LLM).run(state)
    plan = EditingPlan.model_validate(result.editing)
    for seg in plan.segments:
        assert (seg.video_start, seg.video_end) == before[seg.segment_id]


def test_validator_rejects_illegal_ops() -> None:
    plan = EditingSegmentPlan(
        segment_id="x",
        visual_strategy=VisualStrategyBlock(
            operations=[VisualOperation(type="dramatic_camera_rotation", strength=1.0)]
        ),
    )
    out = EditingConstraintValidator().validate_segment(plan)
    assert out.visual_strategy.operations[0].type == "slow_zoom"


def test_enrichment_resolves_audio(tmp_path: Path) -> None:
    mp3 = tmp_path / "tl_001.mp3"
    mp3.write_bytes(b"fake")
    segs = [{
        "id": "tl_001[seg_01]",
        "narration": {"text": "", "audio_path": "", "audio_duration": 0},
    }]
    script = {"narration_segments": [{"segment_id": "tl_001", "text": "Hello kitchen."}]}
    voice = {"segments": [{
        "script_id": "tl_001",
        "audio_path": str(mp3),
        "duration": 2.4,
    }]}
    out = enrich_timeline_narration(segs, script, voice, tmp_path)
    assert out[0]["narration"]["text"] == "Hello kitchen."
    assert out[0]["narration"]["audio_path"] == str(mp3)


def test_visual_planner_maps_slow_push() -> None:
    decision = DirectorDecision(
        visual_goal="show space",
        focus_order=[FocusElement(element="island", priority=1)],
        recommended_style=["wide_shot", "slow_push"],
    )
    tl = _tl_seg("tl_x", "HERO", "highlight", 0.9)
    block = VisualStrategyPlanner().plan(decision, tl)
    assert any(o.type == "slow_zoom" for o in block.operations)


def test_pacing_hero_is_cinematic() -> None:
    decision = DirectorDecision(pacing_hint="slow")
    tl = _tl_seg("tl_x", "HERO", "highlight", 0.9)
    profile = PacingStrategyPlanner().plan(tl, decision)
    assert profile.style == "cinematic"
    assert profile.speed <= 0.85
