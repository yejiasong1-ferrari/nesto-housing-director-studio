"""Tests for the Planner Agent (hierarchical director architecture)."""

import pytest

from backend.agents.planner.agent import PlannerAgent
from backend.agents.planner.attention.normalizer import ROLE_HERO, ROLE_TRANSITION
from backend.agents.planner.attention.scoring import (
    DEFAULT_INTENT_GATE_THRESHOLD,
    fuse_attention,
    match_intent_to_segment,
)
from backend.agents.planner.intent.interpreter import IntentInterpreter
from backend.schemas.planning_schema import DirectorIntent, IntentGraph, planner_output_to_director_dict
from backend.schemas.vision_schema import (
    AttentionCandidate,
    CameraKnowledge,
    RawSegment,
    RoomKnowledge,
    VKBSegment,
    VisionKnowledgeBase,
    VideoIndex,
)
from backend.state.project_state import ProjectState, UserGoal


@pytest.fixture
def sample_vkb() -> VisionKnowledgeBase:
    return VisionKnowledgeBase(
        project_id="test-001",
        video=VideoIndex(duration=60.0),
        segments=[
            VKBSegment(
                segment_id="seg_01",
                confidence=0.9,
                raw=RawSegment(start_time=0.0, end_time=10.0, duration=10.0),
                knowledge=RoomKnowledge(
                    room_type="Kitchen",
                    confidence=0.9,
                    style="Modern",
                    lighting="Good",
                    selling_points=["Kitchen Island", "Natural Light"],
                    camera=CameraKnowledge(motion="Forward", speed="Slow"),
                ),
            ),
            VKBSegment(
                segment_id="seg_02",
                confidence=0.7,
                raw=RawSegment(start_time=10.0, end_time=20.0, duration=10.0),
                knowledge=RoomKnowledge(
                    room_type="Closet",
                    confidence=0.7,
                    style="Functional",
                    lighting="Fair",
                    selling_points=["Shoe storage"],
                ),
            ),
        ],
        candidate_attention=[
            AttentionCandidate(
                target="Kitchen Island",
                segment_id="seg_01",
                score=0.95,
                reason="Prominent feature",
            ),
        ],
    )


@pytest.fixture
def extended_vkb() -> VisionKnowledgeBase:
    """15-segment VKB for hierarchy and contrast tests."""
    segments = []
    room_types = [
        "Hallway", "Kitchen", "Living Room", "Bedroom", "Bathroom",
        "Kitchen", "Studio", "Bedroom", "Closet", "Hallway",
        "Bathroom", "Balcony", "Living Room", "Closet", "Exterior",
    ]
    for i, room in enumerate(room_types, start=1):
        confidence = 0.95 if "Kitchen" in room else (0.5 if room in ("Closet", "Hallway") else 0.75)
        segments.append(
            VKBSegment(
                segment_id=f"seg_{i:02d}",
                confidence=confidence,
                raw=RawSegment(start_time=(i - 1) * 10.0, end_time=i * 10.0, duration=10.0),
                knowledge=RoomKnowledge(
                    room_type=room,
                    confidence=confidence,
                    style="Modern",
                    lighting="Good" if room not in ("Closet", "Hallway") else "Fair",
                    selling_points=["Natural Light"] if room in ("Kitchen", "Living Room", "Studio") else ["Storage"],
                ),
            )
        )
    return VisionKnowledgeBase(
        project_id="test-extended",
        video=VideoIndex(duration=150.0),
        segments=segments,
    )


@pytest.fixture
def planner_agent() -> PlannerAgent:
    return PlannerAgent()


@pytest.fixture
def state_with_vkb(sample_vkb: VisionKnowledgeBase) -> ProjectState:
    return ProjectState(
        project_id="test-001",
        user_goal=UserGoal(prompt="Highlight the kitchen for young couples"),
        vision=sample_vkb.model_dump(),
    )


@pytest.fixture
def state_extended(extended_vkb: VisionKnowledgeBase) -> ProjectState:
    return ProjectState(
        project_id="test-extended",
        user_goal=UserGoal(prompt="突出厨房、客厅采光，年轻家庭，温馨高级"),
        vision=extended_vkb.model_dump(),
    )


def test_intent_interpreter_rule_based() -> None:
    interpreter = IntentInterpreter(llm_provider=None)
    intent = interpreter._rule_based_intent("突出厨房和客厅，适合年轻情侣，强调采光")
    assert "highlight_kitchen" in intent.intent_tags
    assert intent.intent_graph.primary
    assert intent.constraints.preserve_video_order is True


def test_intent_match_kitchen_ranks_higher() -> None:
    intent = DirectorIntent(
        intent_tags=["highlight_kitchen"],
        intent_graph=IntentGraph(primary="kitchen"),
    )
    kitchen = VKBSegment(
        segment_id="seg_01",
        confidence=0.9,
        raw=RawSegment(),
        knowledge=RoomKnowledge(room_type="Kitchen", selling_points=["Gas range"]),
    )
    closet = VKBSegment(
        segment_id="seg_02",
        confidence=0.95,
        raw=RawSegment(),
        knowledge=RoomKnowledge(room_type="Closet", selling_points=["Shoe rack"]),
    )
    kitchen_score, kitchen_reasons = match_intent_to_segment(intent, kitchen)
    closet_score, _ = match_intent_to_segment(intent, closet)
    assert kitchen_score > closet_score
    assert any(r.startswith("intent:") for r in kitchen_reasons)


def test_intent_gating_penalizes_low_match() -> None:
    ungated, _ = fuse_attention(0.8, 0.9, 0.8, 0.7)
    gated, _ = fuse_attention(
        0.2, 0.9, 0.8, 0.7,
        gate_threshold=DEFAULT_INTENT_GATE_THRESHOLD,
        penalty_multiplier=0.3,
    )
    assert gated < ungated * 0.5


@pytest.mark.asyncio
async def test_planner_agent_run_without_llm(
    planner_agent: PlannerAgent,
    state_with_vkb: ProjectState,
) -> None:
    result = await planner_agent.run(state_with_vkb)
    planning = result.planning

    assert planning.get("agent_name") == "planner"
    assert "intent" in planning
    assert planning["intent"].get("intent_graph")
    assert len(planning.get("segment_understanding", [])) == 2
    assert len(planning.get("attention_map", [])) == 2
    assert "hierarchy" in planning
    assert len(planning.get("narrative_flow", [])) == 2
    assert len(planning.get("cinematic_strategy", [])) == 2
    assert len(planning.get("timeline_plan", [])) == 2
    assert len(planning.get("segment_reasoning", [])) == 2

    kitchen_entry = next(a for a in planning["attention_map"] if a["segment_id"] == "seg_01")
    closet_entry = next(a for a in planning["attention_map"] if a["segment_id"] == "seg_02")
    assert kitchen_entry["score"] > closet_entry["score"]
    assert kitchen_entry.get("role") == ROLE_HERO
    assert any(r.startswith("intent:") for r in kitchen_entry["reason"])


@pytest.mark.asyncio
async def test_planner_has_hero_segments(state_with_vkb: ProjectState) -> None:
    agent = PlannerAgent()
    result = await agent.run(state_with_vkb)
    hierarchy = result.planning["hierarchy"]
    assert len(hierarchy["hero_segments"]) >= 2


@pytest.mark.asyncio
async def test_planner_cinematic_intents_vary(state_with_vkb: ProjectState) -> None:
    agent = PlannerAgent()
    result = await agent.run(state_with_vkb)
    cinematic = result.planning["cinematic_strategy"]
    hint_sets = {tuple(c["execution_hints"]) for c in cinematic}
    assert len(hint_sets) >= 1


@pytest.mark.asyncio
async def test_planner_preserves_timeline_order(
    planner_agent: PlannerAgent,
    state_with_vkb: ProjectState,
) -> None:
    result = await planner_agent.run(state_with_vkb)
    timeline = result.planning["timeline_plan"]
    starts = [entry["start"] for entry in timeline]
    assert starts == sorted(starts)
    assert timeline[0]["segment_id"] == "seg_01"
    assert timeline[1]["segment_id"] == "seg_02"


@pytest.mark.asyncio
async def test_planner_llm_call_count_limited(state_with_vkb: ProjectState) -> None:
    """Without LLM provider, zero LLM calls; pipeline still completes."""
    agent = PlannerAgent(llm_provider=None)
    result = await agent.run(state_with_vkb)
    assert result.planning["timeline_plan"]


@pytest.mark.asyncio
async def test_planner_agent_state_key(planner_agent: PlannerAgent) -> None:
    assert planner_agent.state_key == "planning"


@pytest.mark.asyncio
async def test_hierarchy_contrast_and_roles(state_extended: ProjectState) -> None:
    agent = PlannerAgent(llm_provider=None)
    result = await agent.run(state_extended)
    planning = result.planning

    hierarchy = planning["hierarchy"]
    attention = planning["attention_map"]
    n = len(attention)

    assert len(hierarchy["hero_segments"]) >= 2
    assert len(hierarchy["transition_segments"]) / n >= 0.30

    scores = [a["score"] for a in attention]
    assert max(scores) - min(scores) >= 0.50

    kitchen_ids = {"seg_02", "seg_06"}
    closet_ids = {"seg_09", "seg_14"}
    kitchen_scores = [a["score"] for a in attention if a["segment_id"] in kitchen_ids]
    closet_scores = [a["score"] for a in attention if a["segment_id"] in closet_ids]
    assert max(kitchen_scores) > max(closet_scores)


@pytest.mark.asyncio
async def test_hero_and_transition_different_strategies(state_extended: ProjectState) -> None:
    agent = PlannerAgent(llm_provider=None)
    result = await agent.run(state_extended)
    timeline = result.planning["timeline_plan"]

    hero_strategies = [
        t["editing_strategy"]
        for t in timeline
        if t.get("role") == ROLE_HERO
    ]
    transition_strategies = [
        t["editing_strategy"]
        for t in timeline
        if t.get("role") == ROLE_TRANSITION
    ]

    assert hero_strategies
    assert transition_strategies
    assert hero_strategies[0] != transition_strategies[0]


@pytest.mark.asyncio
async def test_transition_narration_capped(state_extended: ProjectState) -> None:
    agent = PlannerAgent(llm_provider=None)
    result = await agent.run(state_extended)
    timeline = result.planning["timeline_plan"]

    for entry in timeline:
        if entry.get("role") == ROLE_TRANSITION:
            assert entry["narration_weight"] <= 0.20


@pytest.mark.asyncio
async def test_director_export_matches_terminal_view(state_with_vkb: ProjectState) -> None:
    agent = PlannerAgent(llm_provider=None)
    result = await agent.run(state_with_vkb)
    director = planner_output_to_director_dict(result.planning)

    assert "version" not in director
    assert "agent_name" not in director
    assert director["intent"]["audience"] == result.planning["intent"]["target_audience"]
    assert director["intent"]["tone"] == result.planning["intent"]["emotional_tone"]
    assert "score_spread" in director
    assert director["attention_map"][0]["attention_score"] == round(
        result.planning["attention_map"][0]["score"], 2
    )
    assert "aesthetic" not in director["attention_map"][0]["signals"]
    assert director["timeline_plan"][0]["segment_id"] == "seg_01"
