"""Tests for the Vision Agent modules."""

import pytest

from backend.agents.vision.modules.preprocessor import VideoPreprocessor
from backend.agents.vision.modules.keyframe_selector import KeyFrameSelector
from backend.schemas.vision_schema import RawSegment, RoomKnowledge, VKBSegment


class TestVideoPreprocessor:
    """Tests for Module 1: Video Preprocessor."""

    def test_build_index_missing_file(self) -> None:
        preprocessor = VideoPreprocessor()
        with pytest.raises(FileNotFoundError):
            preprocessor.build_index("/nonexistent/video.mp4")


class TestKeyFrameSelector:
    """Tests for Module 3: Key Frame Selector."""

    def test_score_frame_missing_file(self) -> None:
        selector = KeyFrameSelector()
        scores = selector.score_frame("/nonexistent/image.jpg")
        assert scores["sharpness"] == 0.0
        assert scores["composite"] == 0.0


class TestKnowledgeFusion:
    """Tests for Module 5: Knowledge Fusion."""

    def test_fuse_room_type_single(self) -> None:
        from backend.agents.vision.modules.fusion import KnowledgeFusionEngine

        engine = KnowledgeFusionEngine()
        analyses = [RoomKnowledge(room_type="Kitchen", confidence=0.95)]
        result = engine.fuse_room_type(analyses)
        assert result == "Kitchen"

    def test_fuse_room_type_open_kitchen(self) -> None:
        from backend.agents.vision.modules.fusion import KnowledgeFusionEngine

        engine = KnowledgeFusionEngine()
        analyses = [
            RoomKnowledge(room_type="Kitchen", confidence=0.9),
            RoomKnowledge(room_type="Dining Area", confidence=0.8),
        ]
        result = engine.fuse_room_type(analyses)
        assert result == "Open Kitchen"

    def test_fuse_selling_points_dedup(self) -> None:
        from backend.agents.vision.modules.fusion import KnowledgeFusionEngine

        engine = KnowledgeFusionEngine()
        analyses = [
            RoomKnowledge(selling_points=["Kitchen Island", "Granite Countertop"]),
            RoomKnowledge(selling_points=["kitchen island", "Hardwood Floors"]),
        ]
        result = engine.fuse_selling_points(analyses)
        assert len(result) == 3  # "kitchen island" deduped

    def test_generate_attention_candidates(self) -> None:
        from backend.agents.vision.modules.fusion import KnowledgeFusionEngine

        engine = KnowledgeFusionEngine()
        segment = VKBSegment(
            segment_id="seg_01",
            confidence=0.85,
            raw=RawSegment(start_time=0, end_time=10, duration=10),
            knowledge=RoomKnowledge(
                room_type="Kitchen",
                confidence=0.85,
                lighting="Excellent",
                selling_points=["Kitchen Island", "Bosch Oven"],
            ),
        )
        candidates = engine.generate_attention_candidates([segment])
        assert len(candidates) == 2
        assert candidates[0].target == "Kitchen Island" or candidates[0].target == "Bosch Oven"
