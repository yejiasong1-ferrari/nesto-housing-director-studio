"""Continuous coverage seals for one-shot walkthrough segmentation."""

from __future__ import annotations

from backend.agents.vision.modules.segmenter import RoomSegmenter
from backend.schemas.vision_schema import RawSegment


def test_seal_continuous_coverage_tiles_full_duration() -> None:
    seg = RoomSegmenter(continuous_coverage=True)
    segments = [
        RawSegment(start_time=9.0, end_time=15.0, duration=6.0, keyframes=[]),
        RawSegment(start_time=15.5, end_time=26.0, duration=10.5, keyframes=[]),
        RawSegment(start_time=27.0, end_time=50.0, duration=23.0, keyframes=[]),
    ]
    sealed = seg._seal_continuous_coverage(segments, total_duration=55.7)
    assert sealed[0].start_time == 0.0
    assert sealed[-1].end_time == 55.7
    for i in range(len(sealed) - 1):
        assert abs(sealed[i].end_time - sealed[i + 1].start_time) < 0.01
        assert sealed[i].duration > 0


def test_leading_short_fragments_are_not_dropped() -> None:
    """Short early boundaries must accumulate into the first keepable segment."""
    segmenter = RoomSegmenter(
        min_segment_duration=3.0,
        continuous_coverage=True,
    )
    # Fake 1fps distances: short chops 0-1, 1-2, then stable room 2-10
    distances = [{"timestamp": float(t), "distance": 0.2 if t in (1, 2) else 0.0} for t in range(11)]
    boundaries = [0, 1, 2]  # boundaries at 0s, 1s, 2s → rest to end
    segments = segmenter.build_segments(distances, boundaries, total_duration=10.0)
    assert segments
    assert segments[0].start_time == 0.0
    assert segments[-1].end_time == 10.0
