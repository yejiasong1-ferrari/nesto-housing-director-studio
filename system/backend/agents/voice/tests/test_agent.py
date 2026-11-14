"""Tests for the Voice Agent (Temporal Voice Director)."""

import pytest

from backend.agents.voice.agent import VoiceAgent
from backend.agents.voice.pipeline.duration_estimator import DurationEstimator
from backend.agents.voice.pipeline.emotional_alignment import EmotionalAlignment
from backend.agents.voice.pipeline.pronunciation import PronunciationController
from backend.agents.voice.pipeline.rhythm_planner import RhythmPlanner
from backend.agents.voice.pipeline.style_selector import StyleSelector
from backend.schemas.voice_schema import VoicePlan, VoiceSegmentPlan
from backend.state.project_state import ProjectState


@pytest.fixture
def sample_script() -> dict:
    return {
        "style": {"tone": "warm_modern_luxury", "sentence_length": "short", "energy": "calm"},
        "narration_segments": [
            {
                "segment_id": "seg_01",
                "text": "Step into the hallway.",
                "arc_stage": "hook",
                "role": "TRANSITION",
                "emotion": "curiosity",
                "start_time": 0.0,
                "end_time": 8.5,
                "scene_duration": 8.5,
            },
            {
                "segment_id": "seg_02",
                "text": "Just ahead, a warm 3-bedroom kitchen with gas range.",
                "arc_stage": "highlight",
                "role": "HERO",
                "emotion": "premium",
                "start_time": 9.0,
                "end_time": 20.5,
                "scene_duration": 11.5,
            },
            {
                "segment_id": "seg_15",
                "text": "A place where every moment feels like home.",
                "arc_stage": "close",
                "role": "SUPPORT",
                "emotion": "warm",
                "start_time": 120.0,
                "end_time": 128.0,
                "scene_duration": 8.0,
            },
        ],
    }


@pytest.fixture
def sample_planning() -> dict:
    return {
        "intent": {
            "target_audience": "young_family",
            "emotional_tone": "warm_modern_luxury",
            "intent_tags": ["highlight_kitchen", "warm_inviting"],
        }
    }


@pytest.fixture
def voice_state(sample_script: dict, sample_planning: dict) -> ProjectState:
    return ProjectState(
        project_id="test-voice-001",
        script=sample_script,
        planning=sample_planning,
    )


def test_style_selector_young_family() -> None:
    profile = StyleSelector().select(
        intent={"target_audience": "young_family", "emotional_tone": "warm_modern_luxury"},
        script_style={"tone": "warm_modern_luxury"},
    )
    assert profile.provider == "volcengine"
    assert profile.style == "family_friendly"
    assert profile.voice_id


def test_pronunciation_three_bedroom() -> None:
    ctrl = PronunciationController()
    text = "A spacious 3-bedroom apartment with 1200 sq ft."
    guide = ctrl.analyze(text)
    spoken = ctrl.apply(text, guide)
    assert "three bedroom" in spoken.lower()
    assert "1200 square feet" in spoken.lower()


def test_rhythm_hook_slower_than_transition() -> None:
    planner = RhythmPlanner()
    hook = planner.plan({"arc_stage": "hook", "role": "TRANSITION", "start_time": 0})
    close = planner.plan({"arc_stage": "close", "role": "SUPPORT"})
    assert close.speed <= hook.speed


def test_duration_estimator_includes_pauses() -> None:
    est = DurationEstimator(base_words_per_second=2.5)
    duration, words, rate = est.estimate_segment(
        "Step into the hallway.",
        delivery_speed=0.9,
        pause_before=0.5,
        pause_after=0.8,
    )
    assert words == 4
    assert duration > 0.5 + 0.8


def test_emotional_alignment_premium() -> None:
    aligner = EmotionalAlignment()
    base = RhythmPlanner().plan({"arc_stage": "highlight", "role": "HERO"})
    aligned = aligner.align({"emotion": "premium"}, base)
    assert aligned.energy == "high"


@pytest.mark.asyncio
async def test_voice_agent_run(voice_state: ProjectState) -> None:
    result = await VoiceAgent().run(voice_state)
    assert result.voice is not None
    assert result.voice.get("agent_name") == "voice"

    plan = VoicePlan.model_validate(result.voice["voice_plan"])
    assert len(plan.segments) == 3
    assert plan.profile.voice_id
    assert plan.timeline_summary.total_scene_duration > 0
    assert plan.timeline_summary.total_estimated_voice_duration > 0

    hero = next(s for s in plan.segments if s.script_id == "seg_02")
    assert "three bedroom" in hero.tts_text.lower()


@pytest.mark.asyncio
async def test_voice_agent_no_tts_in_output(voice_state: ProjectState) -> None:
    result = await VoiceAgent().run(voice_state)
    dumped = str(result.voice)
    assert "audio_path" not in dumped or result.voice.get("voice_plan")
    assert "mp3" not in dumped.lower() or "voice_plan" in dumped


@pytest.mark.asyncio
async def test_voice_agent_requires_script() -> None:
    state = ProjectState(project_id="empty")
    with pytest.raises(ValueError, match="narration_segments"):
        await VoiceAgent().run(state)
