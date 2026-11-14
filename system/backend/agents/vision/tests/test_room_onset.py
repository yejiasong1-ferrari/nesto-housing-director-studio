"""Tests for primary-room onset (room_visible_start) and audio_offset."""

from backend.agents.timeline.pipeline.analyzer import EnrichedSegment
from backend.agents.timeline.pipeline.duration_controller import DurationController
from backend.agents.timeline.pipeline.segment_optimizer import MergeGroup
from backend.agents.vision.modules.room_onset import (
    compute_room_stage,
    compute_room_visible_end,
    compute_room_visible_start,
    enforce_speak_window,
    onset_cap_seconds,
    relative_audio_offset,
)
from backend.schemas.timeline_schema import DurationAdjustmentStrategy


def test_relative_offset_unset_stays_zero() -> None:
    assert relative_audio_offset(40.0, 48.0, 0.0) == 0.0


def test_relative_offset_clamped_to_segment() -> None:
    assert relative_audio_offset(10.0, 18.0, 12.5) == 2.5
    assert relative_audio_offset(10.0, 18.0, 9.0) == 0.0


def test_onset_insufficient_evidence_uses_start() -> None:
    vis = compute_room_visible_start(
        10.0,
        18.0,
        [10.0, 11.0, 12.0, 13.0],
        [0.05, 0.06, 0.07, 0.08],
        [0.20, 0.19, 0.18, 0.17],
        open_plan=True,
    )
    assert vis == 10.0


def test_onset_waits_until_primary_beats_previous() -> None:
    vis = compute_room_visible_start(
        40.0,
        50.0,
        [40.0, 41.0, 42.0, 43.0, 44.0],
        [0.12, 0.15, 0.19, 0.28, 0.32],
        [0.30, 0.28, 0.24, 0.16, 0.12],
        open_plan=True,
    )
    # CLIP says the kitchen only wins at 43s, but open plan cannot tell
    # "walking toward" from "inside" — cap the wait at 1.5s.
    assert vis == 41.5
    assert relative_audio_offset(40.0, 50.0, vis) == 1.5


def test_onset_first_frame_win_does_not_lag() -> None:
    vis = compute_room_visible_start(
        0.0,
        8.0,
        [0.0, 1.0, 2.0],
        [0.40, 0.42, 0.41],
        None,
    )
    assert vis == 0.0


def test_onset_same_label_still_waits_for_primary() -> None:
    """Consecutive Bathroom cuts still wait, but only up to the head-silence cap."""
    vis = compute_room_visible_start(
        73.0,
        81.0,
        [73.0, 75.0, 77.0, 79.0],
        [0.12, 0.16, 0.28, 0.34],
        [0.30, 0.26, 0.18, 0.12],
    )
    assert vis == 75.5
    assert relative_audio_offset(73.0, 81.0, vis) == 2.5


def test_onset_capped_hard_for_same_room_continuation() -> None:
    """Another cut inside the same room — the camera is already there."""
    vis = compute_room_visible_start(
        44.0,
        47.0,
        [44.0, 45.0, 46.0],
        [0.12, 0.30, 0.34],
        [0.30, 0.16, 0.12],
        same_room=True,
    )
    assert relative_audio_offset(44.0, 47.0, vis) <= 0.8


def test_speak_window_never_collapses() -> None:
    """Onset must not meet the exit — that leaves zero seconds to speak."""
    vis, vis_end = enforce_speak_window(70.0, 83.0, 77.8, 77.8)
    assert vis_end - vis >= 1.2
    # 13s shot: trust the segmenter, keep a real share of it speakable.
    assert vis_end - vis >= 0.45 * 13.0 - 0.01
    assert 70.0 <= vis <= vis_end <= 83.0


def test_speak_window_keeps_confirmed_onset_when_room_is_wide_open() -> None:
    vis, vis_end = enforce_speak_window(10.0, 20.0, 12.0, 19.0)
    assert (vis, vis_end) == (12.0, 19.0)


def test_onset_cap_tightens_for_open_plan_and_same_room() -> None:
    assert onset_cap_seconds(20.0) == 2.5
    assert onset_cap_seconds(20.0, open_plan=True) == 1.5
    assert onset_cap_seconds(20.0, same_room=True) == 0.8
    assert onset_cap_seconds(20.0, from_hallway=True) == 4.0
    # Living / kitchen stay on the short cap even if someone passes the flag.
    assert onset_cap_seconds(20.0, open_plan=True, from_hallway=True) == 1.5
    # Short shots stay proportional — never eat a 2s transition whole.
    assert onset_cap_seconds(2.0) <= 0.7


def test_onset_hallway_approach_can_wait_four_seconds() -> None:
    vis = compute_room_visible_start(
        88.0,
        102.0,
        [88.0, 90.0, 92.0, 94.0, 96.0],
        [0.10, 0.12, 0.14, 0.30, 0.36],
        [0.32, 0.30, 0.28, 0.16, 0.10],
        from_hallway=True,
    )
    assert 3.5 <= relative_audio_offset(88.0, 102.0, vis) <= 4.0


def test_visible_end_cuts_when_next_room_wins() -> None:
    vis_end = compute_room_visible_end(
        19.0,
        30.0,
        [19.0, 21.0, 23.0, 25.0, 27.0, 29.0],
        [0.40, 0.38, 0.32, 0.22, 0.12, 0.10],
        [0.10, 0.14, 0.20, 0.30, 0.36, 0.40],
    )
    assert vis_end < 27.0
    assert vis_end >= 19.8


def test_room_stage_from_offset() -> None:
    assert compute_room_stage(0.0) == "interior"
    assert compute_room_stage(0.6) == "entrance"
    assert compute_room_stage(2.0) == "approaching"
    assert compute_room_stage(0.0, left_early=True) == "exiting"


def test_duration_does_not_rewrite_when_video_is_longer() -> None:
    """v3.3: leaving the room does not force a script rewrite; stretch/trim picture."""
    seg = EnrichedSegment(
        segment_id="s1",
        room_type="Bedroom",
        semantic_meaning="",
        video_start=19.0,
        video_end=30.0,
        video_duration=11.0,
        role="SUPPORT",
        importance=0.9,
        arc_stage="explore",
        narrative_function="",
        emotion="neutral",
        narration_weight=0.5,
        narration_text="床头软包。",
        tts_text="床头软包。",
        audio_duration=8.0,
        estimated_duration=8.0,
        audio_path="/tmp/a.mp3",
        delivery_speed=1.0,
        voice_emotion="neutral",
        room_visible_start=19.0,
        room_visible_end=24.0,
        audio_offset=0.0,
    )
    dec = DurationController().decide(MergeGroup(segments=[seg]))
    assert dec.needs_script_rewrite is False
    assert dec.editing_window >= 11.0


def test_duration_rewrites_for_delayed_onset() -> None:
    """Delayed entry is hard: shorten VO instead of slowing or speaking early."""
    seg = EnrichedSegment(
        segment_id="s1",
        room_type="Kitchen",
        semantic_meaning="",
        video_start=40.0,
        video_end=48.0,
        video_duration=8.0,
        role="SUPPORT",
        importance=0.5,
        arc_stage="explore",
        narrative_function="",
        emotion="neutral",
        narration_weight=0.5,
        narration_text="厨房到了。",
        tts_text="厨房到了。",
        audio_duration=6.0,
        estimated_duration=6.0,
        audio_path="/tmp/a.mp3",
        delivery_speed=1.0,
        voice_emotion="neutral",
        room_visible_start=43.0,
        audio_offset=3.0,
    )
    dec = DurationController().decide(MergeGroup(segments=[seg]))
    assert dec.strategy == DurationAdjustmentStrategy.FLAG_REWRITE
    assert dec.needs_script_rewrite is True
    assert dec.editing_window == 8.0
    assert dec.target_audio_duration == 4.6
