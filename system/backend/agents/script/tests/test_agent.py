"""Tests for the Script Agent (Temporal Narration Compiler)."""

import json
from typing import Any

import pytest

from backend.agents.script.agent import ScriptAgent
from backend.agents.script.pipeline.alignment_engine import AlignmentEngine
from backend.agents.script.pipeline.narrative_planner import NarrativePlanner
from backend.agents.script.pipeline.style_controller import StyleController
from backend.agents.script.validators.schema_validator import SchemaValidator
from backend.agents.script.validators.timeline_validator import TimelineValidator
from backend.schemas.script_schema import NarrativeStructure, StyleConfig
from backend.schemas.vision_schema import (
    CameraKnowledge,
    RawSegment,
    RoomKnowledge,
    VKBSegment,
    VideoIndex,
    VisionKnowledgeBase,
)
from backend.services.llm.base import LLMMessage, LLMProvider, LLMResponse
from backend.state.project_state import ProjectState, UserGoal


class _MockLLMProvider(LLMProvider):
    """Returns deterministic narration JSON — avoids real LLM calls in tests.

    Inspects the prompt to find segment_ids in the batch and returns a sentence
    for each one, so it works correctly with batched LLM calls.
    """

    _TEXTS: dict[str, str] = {
        "seg_01": "Step into the sun-drenched hallway, where warmth greets you from the moment you arrive.",
        "seg_02": "The chef's kitchen impresses with a marble island, gleaming stainless appliances, and a gas range built for serious cooking.",
        "seg_03": "Hardwood floors and a sweeping window wall flood the living room with light throughout the day.",
        "seg_04": "Tucked away yet perfectly functional, the walk-in closet offers generous storage right where you need it.",
    }

    async def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        import re
        content = messages[-1].content
        ids_in_prompt = re.findall(r'"segment_id":\s*"(seg_\d+)"', content)
        is_rewrite = "max_words" in content or "Rewrite" in content
        items = []
        for sid in ids_in_prompt:
            if is_rewrite:
                # Return a short version for rewrite tests
                base = self._TEXTS.get(sid, f"A well-appointed space in {sid}.")
                short = " ".join(base.split()[:6]) + "."
                items.append({"segment_id": sid, "text": short})
            else:
                items.append({"segment_id": sid, "text": self._TEXTS.get(sid, f"A well-appointed space in {sid}.")})
        return LLMResponse(content=json.dumps(items), model="mock", finish_reason="stop")

    async def generate_structured(self, messages: list[LLMMessage], response_schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {}


_MOCK_LLM = _MockLLMProvider()


def _seg(seg_id: str, start: float, end: float, room_type: str, selling_points: list[str], **kw) -> VKBSegment:
    return VKBSegment(
        segment_id=seg_id,
        confidence=0.9,
        raw=RawSegment(start_time=start, end_time=end, duration=end - start),
        knowledge=RoomKnowledge(
            room_type=room_type,
            confidence=0.9,
            style=kw.get("style", "Modern"),
            lighting=kw.get("lighting", "Good"),
            selling_points=selling_points,
            furniture=kw.get("furniture", []),
            appliances=kw.get("appliances", []),
            camera=CameraKnowledge(motion="Forward", speed="Slow"),
        ),
    )


@pytest.fixture
def sample_vkb() -> VisionKnowledgeBase:
    return VisionKnowledgeBase(
        project_id="test-001",
        video=VideoIndex(duration=40.0),
        segments=[
            _seg("seg_01", 0.0, 8.0, "Hallway", ["Skylight"]),
            _seg("seg_02", 8.0, 20.0, "Kitchen", ["Marble island", "Large window", "Gas range"]),
            _seg("seg_03", 20.0, 30.0, "Living Room", ["Hardwood floors", "Large window"]),
            _seg("seg_04", 30.0, 32.5, "Closet", ["Walk-in storage"]),
        ],
    )


@pytest.fixture
def sample_planning() -> dict:
    return {
        "intent": {
            "goal": "real_estate_marketing",
            "target_audience": "young_family",
            "intent_tags": ["highlight_kitchen", "warm_inviting", "premium_feel"],
            "emotional_tone": "warm_modern_luxury",
            "intent_graph": {"primary": "kitchen", "secondary": "", "emotional_target": "cozy_premium", "avoid": []},
        },
        "attention_map": [
            {"segment_id": "seg_01", "score": 0.25, "role": "TRANSITION"},
            {"segment_id": "seg_02", "score": 0.95, "role": "HERO"},
            {"segment_id": "seg_03", "score": 0.65, "role": "SUPPORT"},
            {"segment_id": "seg_04", "score": 0.18, "role": "TRANSITION"},
        ],
        "hierarchy": {
            "hero_segments": ["seg_02"],
            "support_segments": ["seg_03"],
            "transition_segments": ["seg_01", "seg_04"],
        },
        "narrative_flow": [
            {"segment_id": "seg_01", "role": "TRANSITION", "emotion": "neutral", "narrative_function": "maintain_spatial_flow", "narration_weight": 0.15},
            {"segment_id": "seg_02", "role": "HERO", "emotion": "warmth", "narrative_function": "showcase_primary_living_feature", "narration_weight": 0.9},
            {"segment_id": "seg_03", "role": "SUPPORT", "emotion": "warmth", "narrative_function": "support_narrative_continuity", "narration_weight": 0.6},
            {"segment_id": "seg_04", "role": "TRANSITION", "emotion": "neutral", "narrative_function": "maintain_spatial_flow", "narration_weight": 0.1},
        ],
        "segment_understanding": [
            {"segment_id": "seg_01", "semantic_meaning": "primary_hallway_showcase", "visual_strength": 0.7, "narrative_potential": 0.2},
            {"segment_id": "seg_02", "semantic_meaning": "primary_kitchen_showcase", "visual_strength": 0.9, "narrative_potential": 0.9},
            {"segment_id": "seg_03", "semantic_meaning": "primary_living_room_showcase", "visual_strength": 0.85, "narrative_potential": 0.7},
            {"segment_id": "seg_04", "semantic_meaning": "primary_closet_showcase", "visual_strength": 0.6, "narrative_potential": 0.2},
        ],
        "timeline_plan": [
            {"segment_id": "seg_01", "start": 0.0, "end": 8.0, "importance": 0.25, "role": "TRANSITION", "narration_weight": 0.15},
            {"segment_id": "seg_02", "start": 8.0, "end": 20.0, "importance": 0.95, "role": "HERO", "narration_weight": 0.9},
            {"segment_id": "seg_03", "start": 20.0, "end": 30.0, "importance": 0.65, "role": "SUPPORT", "narration_weight": 0.6},
            {"segment_id": "seg_04", "start": 30.0, "end": 32.5, "importance": 0.18, "role": "TRANSITION", "narration_weight": 0.1},
        ],
    }


@pytest.fixture
def state_with_context(sample_vkb: VisionKnowledgeBase, sample_planning: dict) -> ProjectState:
    return ProjectState(
        project_id="test-001",
        user_goal=UserGoal(prompt="Highlight the kitchen for a young family, warm premium feel"),
        vision=sample_vkb.model_dump(),
        planning=sample_planning,
    )


@pytest.fixture
def script_agent() -> ScriptAgent:
    return ScriptAgent(llm_provider=_MOCK_LLM)


# ── Module 1: Narrative Planner ──────────────────────────────


def test_narrative_planner_arc_labels(sample_vkb: VisionKnowledgeBase, sample_planning: dict) -> None:
    structure = NarrativePlanner().plan(sample_vkb, sample_planning)
    assert structure.scene_order == ["seg_01", "seg_02", "seg_03", "seg_04"]
    assert structure.story_arc[0] == "hook"
    assert structure.story_arc[-1] == "close"
    assert structure.story_arc[structure.scene_order.index("seg_02")] == "highlight"


# ── Module 3: Style Controller ───────────────────────────────


def test_style_controller_derives_style_from_intent(sample_planning: dict) -> None:
    style = StyleController().derive_style(sample_planning["intent"])
    assert style.tone == "warm_modern_luxury"
    assert style.sentence_length in {"short", "medium", "long"}


def test_style_controller_strips_banned_words() -> None:
    controller = StyleController()
    style = StyleConfig(tone="warm", sentence_length="medium", energy="calm")
    text = controller.apply("A clinical and cold kitchen with an island.", style)
    assert "clinical" not in text
    assert "cold" not in text


def test_style_controller_caps_sentence_length() -> None:
    controller = StyleController()
    style = StyleConfig(tone="professional", sentence_length="short", energy="calm")
    long_text = " ".join(["word"] * 30) + "."
    result = controller.apply(long_text, style)
    assert len(result.split()) <= 14


# ── Module 4: Alignment Engine ───────────────────────────────


def test_alignment_engine_compresses_overlong_text(sample_vkb: VisionKnowledgeBase, sample_planning: dict) -> None:
    structure = NarrativePlanner().plan(sample_vkb, sample_planning)
    style = StyleConfig(tone="professional", sentence_length="medium", energy="calm")
    engine = AlignmentEngine(words_per_minute=150, max_segment_words=100)

    too_long_text = " ".join(["beautiful"] * 40) + "."
    styled = {"seg_04": too_long_text}  # seg_04 is only 2.5s long -> tiny word budget
    for seg in sample_vkb.segments:
        styled.setdefault(seg.segment_id, "A short sentence.")

    segments = engine.align(sample_vkb, sample_planning, structure, styled, style)
    seg_04 = next(s for s in segments if s.segment_id == "seg_04")
    assert seg_04.alignment_status == "compressed"
    assert seg_04.word_count < 40


def test_alignment_engine_extends_short_text(sample_vkb: VisionKnowledgeBase, sample_planning: dict) -> None:
    structure = NarrativePlanner().plan(sample_vkb, sample_planning)
    style = StyleConfig(tone="professional", sentence_length="medium", energy="calm")
    engine = AlignmentEngine(words_per_minute=150, max_segment_words=100)

    styled = {seg.segment_id: "A short sentence." for seg in sample_vkb.segments}
    # seg_03 spans 10s (~25 words at 150wpm) -> far more than the 3-word draft
    segments = engine.align(sample_vkb, sample_planning, structure, styled, style)
    seg_03 = next(s for s in segments if s.segment_id == "seg_03")
    assert seg_03.alignment_status in {"extended", "needs_rewrite"}


def test_alignment_engine_never_shifts_timeline(sample_vkb: VisionKnowledgeBase, sample_planning: dict) -> None:
    structure = NarrativePlanner().plan(sample_vkb, sample_planning)
    style = StyleConfig(tone="professional", sentence_length="medium", energy="calm")
    engine = AlignmentEngine()
    styled = {seg.segment_id: "A pleasant room with natural light." for seg in sample_vkb.segments}

    segments = engine.align(sample_vkb, sample_planning, structure, styled, style)
    for seg, vkb_seg in zip(segments, sorted(sample_vkb.segments, key=lambda s: s.raw.start_time)):
        assert seg.start_time == vkb_seg.raw.start_time
        assert seg.end_time == vkb_seg.raw.end_time


def test_alignment_engine_transition_capped_no_extension(sample_vkb: VisionKnowledgeBase, sample_planning: dict) -> None:
    structure = NarrativePlanner().plan(sample_vkb, sample_planning)
    style = StyleConfig(tone="professional", sentence_length="medium", energy="calm")
    engine = AlignmentEngine()
    styled = {seg.segment_id: "Hallway." for seg in sample_vkb.segments}

    segments = engine.align(sample_vkb, sample_planning, structure, styled, style)
    transition_segs = [s for s in segments if s.role == "TRANSITION"]
    assert transition_segs
    for seg in transition_segs:
        assert seg.alignment_status != "extended"


# ── Validators ────────────────────────────────────────────────


def test_schema_validator_flags_empty_non_transition_text(sample_vkb: VisionKnowledgeBase, sample_planning: dict) -> None:
    structure = NarrativePlanner().plan(sample_vkb, sample_planning)
    style = StyleConfig(tone="professional", sentence_length="medium", energy="calm")
    engine = AlignmentEngine()
    styled = {"seg_02": "", "seg_01": "", "seg_03": "Nice room.", "seg_04": ""}
    segments = engine.align(sample_vkb, sample_planning, structure, styled, style)

    issues = SchemaValidator().validate(segments)
    assert any("seg_02" in issue for issue in issues)


def test_timeline_validator_passes_for_unmodified_order(sample_vkb: VisionKnowledgeBase, sample_planning: dict) -> None:
    structure = NarrativePlanner().plan(sample_vkb, sample_planning)
    style = StyleConfig(tone="professional", sentence_length="medium", energy="calm")
    engine = AlignmentEngine()
    styled = {seg.segment_id: "A pleasant room with natural light and warmth." for seg in sample_vkb.segments}
    segments = engine.align(sample_vkb, sample_planning, structure, styled, style)

    issues = TimelineValidator().validate(sample_vkb, segments, structure)
    assert issues == []


# ── Full Agent Pipeline ───────────────────────────────────────


@pytest.mark.asyncio
async def test_script_agent_run_with_llm(script_agent: ScriptAgent, state_with_context: ProjectState) -> None:
    result = await script_agent.run(state_with_context)
    script = result.script

    assert script.get("agent_name") == "script"
    assert len(script.get("narration_segments", [])) == 4
    assert script["narrative_structure"]["scene_order"] == ["seg_01", "seg_02", "seg_03", "seg_04"]


@pytest.mark.asyncio
async def test_script_agent_requires_llm(state_with_context: ProjectState) -> None:
    """Script Agent must raise RuntimeError when no LLM provider is given."""
    agent_no_llm = ScriptAgent(llm_provider=None)
    with pytest.raises(RuntimeError, match="LLM provider is required"):
        await agent_no_llm.run(state_with_context)


@pytest.mark.asyncio
async def test_script_agent_one_scene_one_narration(script_agent: ScriptAgent, state_with_context: ProjectState) -> None:
    result = await script_agent.run(state_with_context)
    segments = result.script["narration_segments"]
    seg_ids = [s["segment_id"] for s in segments]
    assert len(seg_ids) == len(set(seg_ids))
    for seg in segments:
        assert seg["segment_id"] == seg["scene_id"]


@pytest.mark.asyncio
async def test_script_agent_bound_to_scene_timing(script_agent: ScriptAgent, state_with_context: ProjectState) -> None:
    result = await script_agent.run(state_with_context)
    segments = result.script["narration_segments"]
    vkb = state_with_context.vision["segments"]
    vkb_by_id = {s["segment_id"]: s for s in vkb}

    for seg in segments:
        raw = vkb_by_id[seg["segment_id"]]["raw"]
        assert seg["start_time"] == raw["start_time"]
        assert seg["end_time"] == raw["end_time"]


@pytest.mark.asyncio
async def test_script_agent_hero_gets_richer_narration_than_transition(
    script_agent: ScriptAgent, state_with_context: ProjectState
) -> None:
    result = await script_agent.run(state_with_context)
    segments = result.script["narration_segments"]
    hero = next(s for s in segments if s["role"] == "HERO")
    transition = next(s for s in segments if s["role"] == "TRANSITION")
    assert hero["word_count"] >= transition["word_count"]


@pytest.mark.asyncio
async def test_script_agent_kitchen_narration_has_kitchen_content(
    script_agent: ScriptAgent, state_with_context: ProjectState
) -> None:
    result = await script_agent.run(state_with_context)
    segments = result.script["narration_segments"]
    kitchen_seg = next(s for s in segments if s["segment_id"] == "seg_02")
    text_lower = kitchen_seg["text"].lower()
    assert any(w in text_lower for w in ("kitchen", "island", "marble", "stainless", "gas range"))


@pytest.mark.asyncio
async def test_script_agent_validation_reports_status(script_agent: ScriptAgent, state_with_context: ProjectState) -> None:
    result = await script_agent.run(state_with_context)
    validation = result.script["validation"]
    assert "is_valid" in validation
    assert isinstance(validation["issues"], list)


@pytest.mark.asyncio
async def test_script_agent_requires_planning(script_agent: ScriptAgent, sample_vkb: VisionKnowledgeBase) -> None:
    state = ProjectState(project_id="test-002", vision=sample_vkb.model_dump())
    with pytest.raises(ValueError):
        await script_agent.run(state)


@pytest.mark.asyncio
async def test_script_agent_state_key(script_agent: ScriptAgent) -> None:
    assert script_agent.state_key == "script"


# ── rewrite_for_timeline ──────────────────────────────────────


@pytest.fixture
def state_for_rewrite(script_agent: ScriptAgent, state_with_context: ProjectState):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(script_agent.run(state_with_context))


@pytest.mark.asyncio
async def test_rewrite_for_timeline_llm_shortens_text(
    script_agent: ScriptAgent, state_with_context: ProjectState
) -> None:
    state = await script_agent.run(state_with_context)
    original_text = next(
        s["text"] for s in state.script["narration_segments"] if s["segment_id"] == "seg_02"
    )
    original_words = len(original_text.split())

    rewrite_requests = [
        {
            "source_ids": ["seg_02"],
            "video_duration": 4.0,
            "audio_duration": 12.0,
        }
    ]
    rewritten_state = await script_agent.rewrite_for_timeline(state, rewrite_requests)
    new_text = next(
        s["text"] for s in rewritten_state.script["narration_segments"] if s["segment_id"] == "seg_02"
    )
    new_words = len(new_text.split())
    assert new_words < original_words, "Rewrite should shorten the text"
    assert new_text.strip().endswith("."), "Rewritten text should end with a period"
    assert new_text != original_text, "Text should have changed"


@pytest.mark.asyncio
async def test_rewrite_for_timeline_fallback_trim_when_no_llm(
    state_with_context: ProjectState,
) -> None:
    """When no LLM provider, rewrite falls back to clause_aware_trim."""
    agent_no_llm = ScriptAgent(llm_provider=_MOCK_LLM)
    state = await agent_no_llm.run(state_with_context)

    agent_no_llm.llm_provider = None  # simulate unavailable LLM for rewrite
    rewrite_requests = [{"source_ids": ["seg_02"], "video_duration": 3.0, "audio_duration": 10.0}]
    result = await agent_no_llm.rewrite_for_timeline(state, rewrite_requests)
    new_text = next(s["text"] for s in result.script["narration_segments"] if s["segment_id"] == "seg_02")
    assert len(new_text.split()) < 20


@pytest.mark.asyncio
async def test_rewrite_for_timeline_marks_status(
    script_agent: ScriptAgent, state_with_context: ProjectState
) -> None:
    state = await script_agent.run(state_with_context)
    rewrite_requests = [{"source_ids": ["seg_02"], "video_duration": 3.0, "audio_duration": 10.0}]
    result = await script_agent.rewrite_for_timeline(state, rewrite_requests)
    seg = next(s for s in result.script["narration_segments"] if s["segment_id"] == "seg_02")
    assert seg["alignment_status"] == "rewritten_by_timeline"


@pytest.mark.asyncio
async def test_rewrite_for_timeline_noop_when_no_requests(
    script_agent: ScriptAgent, state_with_context: ProjectState
) -> None:
    state = await script_agent.run(state_with_context)
    result = await script_agent.rewrite_for_timeline(state, [])
    assert result.script == state.script


def test_speaking_rate_english_budget_is_conservative() -> None:
    from backend.agents.script.speaking_rate import (
        EN_WORDS_PER_SECOND,
        ZH_CHARS_PER_SECOND,
        estimated_duration,
        word_budget,
    )

    assert EN_WORDS_PER_SECOND == 2.3
    assert ZH_CHARS_PER_SECOND == 4.2
    # 10s English shot ≈ 23 words (not 25 at 150 wpm)
    assert word_budget(10.0, "en") == 23
    # 10s Chinese shot ≈ 42 characters
    assert word_budget(10.0, "zh") == 42
    text = "Stepping into the kitchen with a gas cooktop."
    # 8 words / 2.3 ≈ 3.48s
    assert estimated_duration(text, "en") == 3.48
    assert estimated_duration("厨房配不锈钢冰箱与通顶橱柜。", "zh") == round(14 / 4.2, 2)

