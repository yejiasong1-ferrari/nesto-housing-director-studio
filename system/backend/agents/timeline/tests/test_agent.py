"""Tests for the Timeline Agent (Narrative Temporal Director)."""

from __future__ import annotations

import pytest

from backend.agents.timeline.agent import TimelineAgent
from backend.agents.timeline.pipeline.analyzer import EnrichedSegment, TimelineAnalyzer
from backend.agents.timeline.pipeline.duration_controller import DurationController
from backend.agents.timeline.pipeline.narrative_flow import NarrativeFlowController
from backend.agents.timeline.pipeline.segment_optimizer import MergeGroup, SegmentOptimizer
from backend.agents.timeline.pipeline.transition_planner import TransitionPlanner
from backend.agents.timeline.validators.timeline_validator import TimelineValidator
from backend.schemas.timeline_schema import (
    DurationAdjustmentStrategy,
    NarrationInfo,
    SourceTiming,
    TimelineOutput,
    TimelineSegment,
    TimelineValidation,
)
from backend.state.project_state import ProjectState


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _seg(
    seg_id: str,
    room_type: str,
    role: str,
    arc: str,
    importance: float,
    video_dur: float,
    audio_dur: float,
    narrative_function: str = "",
    emotion: str = "neutral",
) -> EnrichedSegment:
    return EnrichedSegment(
        segment_id=seg_id,
        room_type=room_type,
        semantic_meaning=f"primary_{room_type.lower()}_showcase",
        video_start=0.0,
        video_end=video_dur,
        video_duration=video_dur,
        role=role,
        importance=importance,
        arc_stage=arc,
        narrative_function=narrative_function,
        emotion=emotion,
        narration_weight=0.5,
        narration_text=f"The {room_type} is well appointed.",
        tts_text=f"The {room_type} is well appointed.",
        audio_duration=audio_dur,
        estimated_duration=audio_dur,
        audio_path=f"/audio/{seg_id}.mp3",
        delivery_speed=0.95,
        voice_emotion="confident",
        focus_elements=["feature_a"],
    )


@pytest.fixture
def kitchen_segments() -> list[EnrichedSegment]:
    return [
        _seg("seg_01", "Kitchen", "SUPPORT", "explore", 0.55, 5.0, 2.5),
        _seg("seg_02", "Kitchen", "SUPPORT", "explore", 0.60, 4.0, 2.0),
    ]


@pytest.fixture
def hero_segment() -> EnrichedSegment:
    return _seg("seg_hero", "Living Room", "HERO", "highlight", 0.95, 8.0, 6.5)


@pytest.fixture
def full_state() -> ProjectState:
    return ProjectState(
        project_id="test-tl-001",
        vision={
            "segments": [
                {
                    "segment_id": "seg_01",
                    "raw": {"start_time": 0.0, "end_time": 8.5, "duration": 8.5},
                    "knowledge": {
                        "room_type": "Hallway",
                        "selling_points": ["skylight"],
                        "furniture": [],
                        "appliances": [],
                        "lighting": "natural",
                        "style": "Modern",
                    },
                },
                {
                    "segment_id": "seg_02",
                    "raw": {"start_time": 9.0, "end_time": 20.5, "duration": 11.5},
                    "knowledge": {
                        "room_type": "Kitchen",
                        "selling_points": ["marble island", "stainless appliances"],
                        "furniture": [],
                        "appliances": ["gas range"],
                        "lighting": "natural",
                        "style": "Modern",
                    },
                },
                {
                    "segment_id": "seg_03",
                    "raw": {"start_time": 21.0, "end_time": 29.0, "duration": 8.0},
                    "knowledge": {
                        "room_type": "Living Room",
                        "selling_points": ["hardwood floors", "large windows"],
                        "furniture": ["sofa"],
                        "appliances": [],
                        "lighting": "natural",
                        "style": "Modern",
                    },
                },
            ]
        },
        planning={
            "intent": {"emotional_tone": "warm_modern_luxury", "target_audience": "young_family"},
            "attention_map": [
                {"segment_id": "seg_01", "score": 0.30, "role": "TRANSITION"},
                {"segment_id": "seg_02", "score": 0.85, "role": "HERO"},
                {"segment_id": "seg_03", "score": 0.60, "role": "SUPPORT"},
            ],
            "hierarchy": {
                "hero_segments": ["seg_02"],
                "support_segments": ["seg_03"],
                "transition_segments": ["seg_01"],
            },
            "narrative_flow": [
                {"segment_id": "seg_01", "role": "TRANSITION", "emotion": "curiosity", "narrative_function": "establish_entry", "narration_weight": 0.15},
                {"segment_id": "seg_02", "role": "HERO", "emotion": "premium", "narrative_function": "showcase_primary_kitchen", "narration_weight": 0.9},
                {"segment_id": "seg_03", "role": "SUPPORT", "emotion": "warmth", "narrative_function": "support_narrative_continuity", "narration_weight": 0.6},
            ],
            "segment_understanding": [
                {"segment_id": "seg_01", "semantic_meaning": "hallway_showcase", "visual_strength": 0.7, "narrative_potential": 0.2},
                {"segment_id": "seg_02", "semantic_meaning": "kitchen_showcase", "visual_strength": 0.9, "narrative_potential": 0.9},
                {"segment_id": "seg_03", "semantic_meaning": "living_room_showcase", "visual_strength": 0.8, "narrative_potential": 0.7},
            ],
            "timeline_plan": [
                {"segment_id": "seg_01", "start": 0.0, "end": 8.5},
                {"segment_id": "seg_02", "start": 9.0, "end": 20.5},
                {"segment_id": "seg_03", "start": 21.0, "end": 29.0},
            ],
        },
        script={
            "narrative_structure": {
                "scene_order": ["seg_01", "seg_02", "seg_03"],
                "story_arc": ["hook", "highlight", "explore"],
            },
            "narration_segments": [
                {"segment_id": "seg_01", "text": "Step into a bright hallway.", "arc_stage": "hook", "role": "TRANSITION", "emotion": "curiosity", "start_time": 0.0, "end_time": 8.5, "scene_duration": 8.5, "importance": 0.30, "room_type": "Hallway"},
                {"segment_id": "seg_02", "text": "The kitchen features a marble island.", "arc_stage": "highlight", "role": "HERO", "emotion": "premium", "start_time": 9.0, "end_time": 20.5, "scene_duration": 11.5, "importance": 0.85, "room_type": "Kitchen"},
                {"segment_id": "seg_03", "text": "Hardwood floors and large windows create warmth.", "arc_stage": "explore", "role": "SUPPORT", "emotion": "warmth", "start_time": 21.0, "end_time": 29.0, "scene_duration": 8.0, "importance": 0.60, "room_type": "Living Room"},
            ],
        },
        voice={
            "agent_name": "voice",
            "voice_plan": {
                "profile": {"voice_id": "test_speaker", "provider": "volcengine"},
                "segments": [
                    {"id": "voice_001", "script_id": "seg_01", "text": "Step into a bright hallway.", "tts_text": "Step into a bright hallway.", "delivery": {"speed": 0.95, "emotion": "curious"}, "estimated_duration": 3.5, "scene_duration": 8.5},
                    {"id": "voice_002", "script_id": "seg_02", "text": "The kitchen features a marble island.", "tts_text": "The kitchen features a marble island.", "delivery": {"speed": 0.90, "emotion": "premium"}, "estimated_duration": 7.2, "scene_duration": 11.5},
                    {"id": "voice_003", "script_id": "seg_03", "text": "Hardwood floors and large windows create warmth.", "tts_text": "Hardwood floors and large windows create warmth.", "delivery": {"speed": 0.90, "emotion": "warm"}, "estimated_duration": 6.0, "scene_duration": 8.0},
                ],
            },
        },
    )


# ── Module 1: Analyzer ────────────────────────────────────────────────────────

def test_analyzer_produces_correct_segment_count(full_state: ProjectState) -> None:
    analyzer = TimelineAnalyzer()
    enriched = analyzer.analyze(
        full_state.vision, full_state.planning,
        full_state.script,
        full_state.voice.get("voice_plan", {}),
        {},
    )
    assert len(enriched) == 3


def test_analyzer_hero_role_propagated(full_state: ProjectState) -> None:
    analyzer = TimelineAnalyzer()
    enriched = analyzer.analyze(
        full_state.vision, full_state.planning,
        full_state.script,
        full_state.voice.get("voice_plan", {}),
        {},
    )
    hero = next(e for e in enriched if e.segment_id == "seg_02")
    assert hero.role == "HERO"
    assert hero.importance >= 0.8


# ── Module 2: Segment Optimizer ───────────────────────────────────────────────

def test_optimizer_never_merges_hero(hero_segment: EnrichedSegment, kitchen_segments: list[EnrichedSegment]) -> None:
    segs = kitchen_segments[:1] + [hero_segment]
    groups = SegmentOptimizer().optimize(segs)
    for group in groups:
        if hero_segment.segment_id in [s.segment_id for s in group.segments]:
            assert len(group.segments) == 1, "HERO segment must not be merged"


def test_optimizer_merges_same_room_low_importance(kitchen_segments: list[EnrichedSegment]) -> None:
    groups = SegmentOptimizer().optimize(kitchen_segments)
    assert len(groups) < len(kitchen_segments), "Same-room low-importance segments should be merged"


def _place(seg: EnrichedSegment, start: float, end: float) -> EnrichedSegment:
    seg.video_start = start
    seg.video_end = end
    seg.video_duration = end - start
    return seg


def test_optimizer_merges_consecutive_hero_shots_of_one_room() -> None:
    """Three kitchen beats in a row read as 'we ran out of kitchen footage'."""
    a = _place(_seg("k1", "Kitchen", "HERO", "highlight", 0.9, 3.0, 2.0), 44.0, 47.0)
    b = _place(_seg("k2", "Kitchen", "HERO", "highlight", 0.9, 4.0, 2.5), 47.0, 51.0)
    groups = SegmentOptimizer().optimize([a, b])
    assert len(groups) == 1


def test_optimizer_absorbs_thin_kitchen_window_after_hero() -> None:
    a = _place(_seg("k1", "Kitchen", "HERO", "highlight", 0.9, 14.0, 12.0), 30.0, 44.0)
    b = _place(_seg("k2", "Kitchen", "HERO", "highlight", 0.9, 7.0, 6.0), 44.0, 51.0)
    b.narration_text = "落地大窗引入城市景观，哑光灰橱柜线条利落。"
    b.tts_text = b.narration_text
    groups = SegmentOptimizer().optimize([a, b])
    assert len(groups) == 1


def test_optimizer_keeps_dishwasher_closeup_separate() -> None:
    a = _place(_seg("k1", "Kitchen", "SUPPORT", "explore", 0.6, 13.0, 12.0), 0.0, 13.0)
    b = _place(_seg("k2", "Kitchen", "HERO", "highlight", 0.85, 4.0, 4.5), 13.0, 17.0)
    b.narration_text = "嵌入式洗碗机门已打开，内篮清晰可见。"
    b.tts_text = b.narration_text
    b.focus_elements = ["dishwasher"]
    groups = SegmentOptimizer().optimize([a, b])
    assert len(groups) == 2


def test_optimizer_keeps_distinct_bedroom_beats_separate() -> None:
    view_only = _place(_seg("bed_view", "Bedroom", "SUPPORT", "explore", 0.6, 7.0, 3.0), 24.0, 31.0)
    view_only.focus_elements = ["harbor view", "large window"]
    view_only.narration_text = "落地窗展现港湾与城市全景。"
    bed_workspace = _place(_seg("bed_sleep", "Bedroom", "SUPPORT", "explore", 0.6, 4.0, 3.0), 31.0, 35.0)
    bed_workspace.focus_elements = ["bed", "desk", "laptop", "wardrobe"]
    bed_workspace.narration_text = "卧室里有床、书桌和衣柜。"
    bed_workspace.room_stage = "entrance"

    groups = SegmentOptimizer().optimize([view_only, bed_workspace])

    assert len(groups) == 2


def test_optimizer_does_not_merge_three_private_room_beats() -> None:
    a = _place(_seg("bed_a", "Bedroom", "SUPPORT", "explore", 0.55, 3.0, 2.0), 30.0, 33.0)
    b = _place(_seg("bed_b", "Bedroom", "SUPPORT", "explore", 0.55, 3.0, 2.0), 33.0, 36.0)
    c = _place(_seg("bed_c", "Bedroom", "SUPPORT", "explore", 0.55, 3.0, 2.0), 36.0, 39.0)
    for seg in (a, b, c):
        seg.focus_elements = ["bed", "window"]

    groups = SegmentOptimizer().optimize([a, b, c])

    assert [len(g.segments) for g in groups] == [2, 1]


def test_optimizer_still_protects_a_hero_in_a_different_room() -> None:
    a = _place(_seg("k1", "Kitchen", "SUPPORT", "explore", 0.5, 4.0, 2.0), 40.0, 44.0)
    hero = _place(_seg("lr", "Living Room", "HERO", "highlight", 0.95, 8.0, 6.5), 44.0, 52.0)
    groups = SegmentOptimizer().optimize([a, hero])
    assert len(groups) == 2


def test_optimizer_absorbs_an_unplaceable_shot_into_its_neighbour() -> None:
    """An Unknown shot has no room, so alone it narrates the skyline as filler."""
    bedroom = _place(_seg("b1", "Bedroom", "SUPPORT", "explore", 0.6, 11.0, 9.0), 40.0, 51.0)
    orphan = _place(_seg("u1", "Unknown", "TRANSITION", "explore", 0.3, 5.0, 3.0), 51.0, 56.0)
    groups = SegmentOptimizer().optimize([bedroom, orphan])
    assert len(groups) == 1
    assert [s.segment_id for s in groups[0].segments] == ["b1", "u1"]


def test_optimizer_leaves_a_long_unplaceable_shot_alone() -> None:
    bedroom = _place(_seg("b1", "Bedroom", "SUPPORT", "explore", 0.6, 11.0, 9.0), 40.0, 51.0)
    long_orphan = _place(_seg("u1", "Unknown", "SUPPORT", "explore", 0.5, 12.0, 9.0), 51.0, 63.0)
    groups = SegmentOptimizer().optimize([bedroom, long_orphan])
    assert len(groups) == 2


def test_optimizer_merges_two_angles_of_one_bathroom() -> None:
    """Otherwise both lines list the same toilet and tub and imply two baths."""
    a = _place(_seg("ba1", "Bathroom", "SUPPORT", "explore", 0.6, 8.0, 6.0), 60.0, 68.0)
    b = _place(_seg("ba2", "Bathroom", "SUPPORT", "explore", 0.6, 7.0, 5.5), 68.0, 75.0)
    groups = SegmentOptimizer().optimize([a, b])
    assert len(groups) == 1


def test_optimizer_keeps_feature_emotion_separate() -> None:
    feature = _seg("feat", "Kitchen", "SUPPORT", "explore", 0.50, 4.0, 2.0, "showcase_primary_kitchen")
    emotion = _seg("emot", "Kitchen", "SUPPORT", "highlight", 0.60, 4.0, 2.0, "emotional_resonance", "warmth")
    groups = SegmentOptimizer().optimize([feature, emotion])
    assert len(groups) == 2, "Feature→Emotion sequence must NOT be merged"


# ── Module 3: Duration Controller ─────────────────────────────────────────────

def test_duration_no_adjustment_within_tolerance() -> None:
    seg = _seg("s1", "Kitchen", "SUPPORT", "explore", 0.6, 6.0, 5.8)
    group = MergeGroup(segments=[seg])
    dec = DurationController().decide(group)
    assert dec.strategy == DurationAdjustmentStrategy.NO_ADJUSTMENT


def test_duration_slow_motion_for_important_over_budget() -> None:
    seg = _seg("s1", "Kitchen", "HERO", "highlight", 0.90, 8.0, 10.5)
    group = MergeGroup(segments=[seg])
    dec = DurationController().decide(group)
    assert dec.strategy == DurationAdjustmentStrategy.SLOW_MOTION
    assert dec.extension_factor < 1.0


def test_duration_rewrites_short_closeup_instead_of_slowmo() -> None:
    seg = _seg("s1", "Kitchen", "TRANSITION", "explore", 0.90, 4.0, 5.5)
    group = MergeGroup(segments=[seg])
    dec = DurationController().decide(group)
    assert dec.strategy == DurationAdjustmentStrategy.FLAG_REWRITE
    assert dec.needs_script_rewrite is True


def test_duration_flag_rewrite_for_low_importance_over_budget() -> None:
    seg = _seg("s1", "Closet", "TRANSITION", "explore", 0.20, 3.0, 8.0)
    group = MergeGroup(segments=[seg])
    dec = DurationController().decide(group)
    assert dec.strategy == DurationAdjustmentStrategy.FLAG_REWRITE
    assert dec.needs_script_rewrite is True


def test_duration_trim_when_video_much_longer() -> None:
    seg = _seg("s1", "Hallway", "TRANSITION", "explore", 0.30, 15.0, 2.0)
    group = MergeGroup(segments=[seg])
    dec = DurationController().decide(group)
    assert dec.strategy in (
        DurationAdjustmentStrategy.TRIM_VIDEO,
        DurationAdjustmentStrategy.INSERT_VISUAL_ACCENT,
    )


def test_duration_uses_full_source_span_not_sum() -> None:
    """Merged group with a gap: window must cover end−start, not sum of parts."""
    a = _seg("a", "Dining", "SUPPORT", "explore", 0.5, 3.5, 2.0)
    a.video_start = 27.0
    a.video_end = 30.5
    a.video_duration = 3.5
    b = _seg("b", "Dining", "SUPPORT", "explore", 0.5, 6.5, 3.0)
    b.video_start = 31.0
    b.video_end = 37.5
    b.video_duration = 6.5
    group = MergeGroup(segments=[a, b])
    dec = DurationController().decide(group)
    assert dec.video_duration == 10.5  # 37.5 - 27.0, includes 0.5s gap
    assert dec.editing_window >= 10.5


# ── Module 4: Narrative Flow ──────────────────────────────────────────────────

def test_flow_hook_is_opening_hook() -> None:
    seg = _seg("s1", "Hallway", "TRANSITION", "hook", 0.3, 8.0, 3.0)
    plans = NarrativeFlowController().plan([MergeGroup(segments=[seg])], total_groups=5)
    assert plans[0].story_phase == "opening_hook"
    assert plans[0].pace == "slow"


def test_flow_hero_highlight_is_emotional_center() -> None:
    seg = _seg("s1", "Living Room", "HERO", "highlight", 0.95, 10.0, 7.0)
    plans = NarrativeFlowController().plan([MergeGroup(segments=[seg])], total_groups=5)
    assert plans[0].story_phase == "emotional_center"
    assert plans[0].pace == "slow"


def test_flow_close_is_signature_close() -> None:
    seg = _seg("s1", "Exterior", "TRANSITION", "close", 0.2, 3.0, 1.5)
    plans = NarrativeFlowController().plan([MergeGroup(segments=[seg])], total_groups=5)
    assert plans[0].story_phase == "signature_close"


# ── Module 5: Transition Planner ──────────────────────────────────────────────

def test_transition_same_room_is_cut() -> None:
    a = _seg("a", "Kitchen", "SUPPORT", "explore", 0.5, 4.0, 2.0)
    b = _seg("b", "Kitchen", "SUPPORT", "explore", 0.5, 4.0, 2.0)
    trans = TransitionPlanner().plan_all([MergeGroup([a]), MergeGroup([b])])
    assert trans[0]["type"] == "cut"


def test_transition_to_hero_is_soft_pan() -> None:
    a = _seg("a", "Hallway", "TRANSITION", "hook", 0.3, 8.0, 2.0)
    b = _seg("b", "Kitchen", "HERO", "highlight", 0.9, 10.0, 7.0)
    trans = TransitionPlanner(continuous_walkthrough=False).plan_all(
        [MergeGroup([a]), MergeGroup([b])]
    )
    assert trans[0]["type"] == "soft_pan"


def test_transition_interior_to_exterior_is_fade() -> None:
    a = _seg("a", "Bedroom", "SUPPORT", "explore", 0.5, 6.0, 4.0)
    b = _seg("b", "Exterior", "TRANSITION", "close", 0.2, 3.0, 1.5)
    trans = TransitionPlanner(continuous_walkthrough=False).plan_all(
        [MergeGroup([a]), MergeGroup([b])]
    )
    assert trans[0]["type"] == "fade"


def test_continuous_walkthrough_forces_cut() -> None:
    a = _seg("a", "Hallway", "TRANSITION", "hook", 0.3, 8.0, 2.0)
    b = _seg("b", "Kitchen", "HERO", "highlight", 0.9, 10.0, 7.0)
    trans = TransitionPlanner(continuous_walkthrough=True).plan_all(
        [MergeGroup([a]), MergeGroup([b])]
    )
    assert trans[0]["type"] in ("cut", "quick_cut")
    assert trans[0]["duration"] == 0.0
    assert trans[1]["type"] == "cut"


# ── Module 6: Validator ───────────────────────────────────────────────────────

def test_validator_flags_audio_exceeds_window() -> None:
    seg = TimelineSegment(
        id="tl_001", source_ids=["seg_01"],
        source=SourceTiming(video_start=0, video_end=5, video_duration=5),
        narration=NarrationInfo(audio_duration=9.0),
        duration_decision=__import__("backend.schemas.timeline_schema", fromlist=["DurationDecision"]).DurationDecision(editing_window=6.0),
        timeline_start=0, timeline_end=6,
    )
    output = TimelineOutput(project_id="x", total_duration=6, segments=[seg])
    val = TimelineValidator().validate(output)
    assert not val.is_valid
    assert any("tl_001" in iss for iss in val.issues)


def test_validator_flags_missing_hero() -> None:
    seg = TimelineSegment(
        id="tl_001", source_ids=["seg_01"],
        source=SourceTiming(video_duration=5),
        narration=NarrationInfo(audio_duration=3.0),
        duration_decision=__import__("backend.schemas.timeline_schema", fromlist=["DurationDecision"]).DurationDecision(editing_window=5.0),
        timeline_start=0, timeline_end=5,
    )
    output = TimelineOutput(project_id="x", total_duration=5, segments=[seg])
    val = TimelineValidator().validate(output, hero_segment_ids=["seg_hero_missing"])
    assert not val.is_valid
    assert val.must_show_coverage.get("seg_hero_missing") is False


# ── Full Agent Pipeline ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeline_agent_run(full_state: ProjectState) -> None:
    result = await TimelineAgent().run(full_state)
    assert result.timeline is not None
    output = result.timeline
    assert output.get("agent_name") == "timeline"
    assert output.get("total_duration", 0) > 0
    assert len(output.get("segments", [])) > 0


@pytest.mark.asyncio
async def test_timeline_agent_hero_not_merged(full_state: ProjectState) -> None:
    result = await TimelineAgent().run(full_state)
    for seg in result.timeline.get("segments", []):
        if "seg_02" in seg.get("source_ids", []):
            assert seg.get("merge", {}).get("decision") != "MERGED_HEAD" or len(seg["source_ids"]) == 1


@pytest.mark.asyncio
async def test_timeline_agent_hero_coverage(full_state: ProjectState) -> None:
    result = await TimelineAgent().run(full_state)
    validation = result.timeline.get("validation", {})
    coverage = validation.get("must_show_coverage", {})
    assert coverage.get("seg_02") is True


@pytest.mark.asyncio
async def test_timeline_agent_state_key() -> None:
    assert TimelineAgent().state_key == "timeline"


@pytest.mark.asyncio
async def test_timeline_agent_requires_script() -> None:
    state = ProjectState(project_id="empty", script={})
    with pytest.raises(ValueError, match="narration_segments"):
        await TimelineAgent().run(state)


@pytest.mark.asyncio
async def test_refine_with_audio_preserves_delayed_onset_and_flags_rewrite() -> None:
    """Final audio fitting must not move narration back before room entry."""
    state = ProjectState(
        project_id="delayed-entry",
        script={
            "narration_segments": [
                {"segment_id": "tl_001", "text": "卫生间配备马桶、淋浴和台盆。"}
            ]
        },
        voice={
            "segments": [
                {"script_id": "tl_001", "duration": 6.0, "audio_path": ""}
            ]
        },
        timeline={
            "segments": [
                {
                    "id": "tl_001",
                    "source_ids": ["tl_001"],
                    "room_type": "Bathroom",
                    "source": {"video_start": 6.0, "video_end": 14.0, "video_duration": 8.0},
                    "narration": {"text": "卫生间配备马桶、淋浴和台盆。", "audio_duration": 4.0},
                    "duration_decision": {"editing_window": 8.0, "video_duration": 8.0},
                    "transition": {"duration": 0.0, "type": "cut"},
                    "audio_offset": 3.0,
                }
            ]
        },
    )

    result = await TimelineAgent().refine_with_audio(state)
    seg = result.timeline["segments"][0]
    dd = seg["duration_decision"]
    assert seg["audio_offset"] == 3.0
    assert dd["strategy"] == "flag_rewrite"
    assert dd["needs_script_rewrite"] is True
    assert dd["target_audio_duration"] == 4.6
