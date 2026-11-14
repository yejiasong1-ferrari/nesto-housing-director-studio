"""Tests for Evaluation Agent (single feedback loop)."""

import pytest

from backend.agents.evaluation.agent import EvaluationAgent
from backend.agents.evaluation.evaluators.audio_visual import AudioVisualEvaluator
from backend.agents.evaluation.feedback.router import FeedbackRouter
from backend.schemas.evaluation_schema import EvaluationResult, FixAction, PriorityFix
from backend.state.project_state import ProjectState


def _state_with_mismatch() -> ProjectState:
    """Kitchen narration but video_start still in hallway-ish gap — use vision kitchen late."""
    return ProjectState(
        project_id="test-eval",
        vision={
            "segments": [
                {
                    "segment_id": "seg_01",
                    "raw": {"start_time": 0.0, "end_time": 8.5, "room_type": "Hallway"},
                    "knowledge": {"room_type": "Hallway"},
                },
                {
                    "segment_id": "seg_02",
                    "raw": {"start_time": 9.0, "end_time": 25.0, "room_type": "Kitchen"},
                    "knowledge": {"room_type": "Kitchen", "selling_points": ["marble island"]},
                },
            ]
        },
        planning={"hierarchy": {"hero_segments": ["seg_02"]}},
        timeline={
            "total_duration": 20.0,
            "segments": [
                {
                    "id": "tl_001",
                    "source_ids": ["seg_01"],
                    "room_type": "Kitchen",  # mismatched label vs vision at start
                    "role": "HERO",
                    "importance": 0.9,
                    "source": {"video_start": 0.0, "video_end": 8.5, "video_duration": 8.5},
                    "narration": {
                        "text": "Warm wood cabinets frame the marble island and gas range.",
                        "audio_duration": 6.0,
                        "audio_path": "/tmp/x.mp3",
                    },
                    "visual_plan": {"focus_elements": ["marble island"]},
                    "duration_decision": {"editing_window": 8.5, "strategy": "trim_video"},
                }
            ],
        },
        script={
            "narration_segments": [
                {
                    "segment_id": "tl_001",
                    "text": "Warm wood cabinets frame the marble island and gas range.",
                    "room_type": "Kitchen",
                }
            ]
        },
        editing={
            "segments": [
                {
                    "segment_id": "tl_001",
                    "role": "HERO",
                    "room_type": "Kitchen",
                    "narration_text": "Warm wood cabinets frame the marble island and gas range.",
                    "audio_path": "/tmp/x.mp3",
                    "audio_duration": 6.0,
                    "editing_window": 8.5,
                    "video_start": 0.0,
                    "video_end": 8.5,
                    "subtitle": {"enabled": True},
                    "visual_strategy": {
                        "focus": ["cabinet"],
                        "operations": [{"type": "clean_cut", "target": "cabinet", "parameters": {}}],
                    },
                    "visual_strategies": [{"type": "clean_cut", "parameters": {}}],
                }
            ]
        },
        render={
            "status": "success",
            "duration": 8.5,
            "fps": 30,
            "width": 1920,
            "height": 1080,
            "output_path": "/tmp/missing_on_purpose.mp4",
            "segments": [
                {"segment_id": "tl_001", "duration": 8.5, "audio_mixed": True, "subtitle_burned": True}
            ],
        },
        voice={"segments": [{"script_id": "tl_001", "duration": 6.0}]},
    )


@pytest.mark.asyncio
async def test_evaluation_detects_semantic_mismatch() -> None:
    state = _state_with_mismatch()
    result = await EvaluationAgent(llm_provider=None).run(state)
    assert result.evaluation.get("agent_name") == "evaluation"
    er = EvaluationResult.model_validate(result.evaluation)
    types = {i.type for i in er.issues}
    assert "semantic_mismatch" in types or "hero_underemphasized" in types
    assert er.feedback_round == 1


@pytest.mark.asyncio
async def test_av_evaluator_flags_kitchen_on_hallway_frame() -> None:
    state = _state_with_mismatch()
    score, issues = AudioVisualEvaluator().evaluate(
        state.timeline, state.script, state.editing, state.vision, state.planning, state.voice,
    )
    assert any(i.type == "semantic_mismatch" for i in issues)
    assert score < 100


def test_feedback_router_shifts_video_start() -> None:
    state = _state_with_mismatch()
    fix = PriorityFix(
        id="fix_001",
        target_agent="timeline_agent",
        segment="tl_001",
        problem="kitchen narration on hallway",
        action=FixAction(type="shift_video_start", value=2.0),
        severity="high",
    )
    out = FeedbackRouter(continuous_walkthrough=False).apply(
        [fix],
        timeline=state.timeline,
        editing=state.editing,
        script=state.script,
    )
    tl = out["timeline"]["segments"][0]
    assert tl["source"]["video_start"] == 2.0
    assert out["editing"]["segments"][0]["video_start"] == 2.0


def test_feedback_router_skips_shift_in_continuous_mode() -> None:
    state = _state_with_mismatch()
    fix = PriorityFix(
        id="fix_001b",
        target_agent="timeline_agent",
        segment="tl_001",
        problem="kitchen narration on hallway",
        action=FixAction(type="shift_video_start", value=2.0),
        severity="high",
    )
    out = FeedbackRouter(continuous_walkthrough=True).apply(
        [fix],
        timeline=state.timeline,
        editing=state.editing,
        script=state.script,
    )
    tl = out["timeline"]["segments"][0]
    assert tl["source"]["video_start"] == 0.0


def test_feedback_router_adds_emphasis() -> None:
    state = _state_with_mismatch()
    fix = PriorityFix(
        id="fix_002",
        target_agent="editing_agent",
        segment="tl_001",
        problem="hero flat",
        action=FixAction(type="add_emphasis", target="slow_zoom"),
    )
    out = FeedbackRouter().apply(
        [fix],
        timeline=state.timeline,
        editing=state.editing,
        script=state.script,
    )
    ops = out["editing"]["segments"][0]["visual_strategy"]["operations"]
    assert ops[0]["type"] == "slow_zoom"


def test_shorten_subtitle_does_not_change_spoken_text() -> None:
    state = _state_with_mismatch()
    original = state.script["narration_segments"][0]["text"]
    fix = PriorityFix(
        id="fix_sub",
        target_agent="script_agent",
        segment="tl_001",
        problem="subtitle too long",
        action=FixAction(type="shorten_subtitle", value=90),
    )
    out = FeedbackRouter().apply(
        [fix],
        timeline=state.timeline,
        editing=state.editing,
        script=state.script,
    )
    assert out["script"]["narration_segments"][0]["text"] == original
    assert out["needs_tts_segments"] == []
    assert out["editing"]["segments"][0]["narration_text"] == original


def test_render_resolution_is_ignored() -> None:
    from backend.agents.evaluation.evaluators.technical import TechnicalEvaluator

    score, issues = TechnicalEvaluator().evaluate(
        {"status": "success", "fps": 30, "width": 1080, "height": 1920, "output_path": ""},
        {"segments": []},
        {"segments": []},
    )
    assert score == 100
    assert not any(i.type == "encoding" for i in issues)

    tiny_score, tiny_issues = TechnicalEvaluator().evaluate(
        {"status": "success", "fps": 30, "width": 640, "height": 360, "output_path": ""},
        {"segments": []},
        {"segments": []},
    )
    assert tiny_score == 100
    assert not any(i.type == "encoding" for i in tiny_issues)


def test_router_skips_unsupported_rendering_action() -> None:
    state = _state_with_mismatch()
    fix = PriorityFix(
        id="fix_enc",
        target_agent="rendering_agent",
        action=FixAction(type="extend_window", value=0.5),
        problem="Low resolution 1080x1920",
    )
    out = FeedbackRouter().apply(
        [fix],
        timeline=state.timeline,
        editing=state.editing,
        script=state.script,
        audio_config={"background_music": {"enabled": True, "volume_db": -18.0}},
    )
    assert out["applied"] == []
    assert out["needs_tts_segments"] == []


def test_critic_skips_resolution_nits() -> None:
    from backend.agents.evaluation.critic.llm_critic import LLMCritic
    from backend.schemas.evaluation_schema import EvaluationIssue

    fixes = LLMCritic()._rule_critique([
        EvaluationIssue(
            type="encoding",
            description="Low resolution 1080x1920",
            suggested_target="rendering",
        )
    ])
    assert fixes == []


@pytest.mark.asyncio
async def test_state_key() -> None:
    assert EvaluationAgent().state_key == "evaluation"
