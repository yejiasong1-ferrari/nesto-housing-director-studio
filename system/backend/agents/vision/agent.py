"""Vision Agent - Spatial Perception Engine.

The Vision Agent is the entire AI Director system's Perception Layer.
It transforms a continuous walkthrough video into a Vision Knowledge Base (VKB)
that all downstream agents consume.

Principle: Perceive Once, Reuse Everywhere.

Pipeline:
    1. Video Preprocessing   → VideoIndex (metadata, sample frames)
    2. Room Segmentation     → Raw segments (temporal boundaries)
    3. Key Frame Selection   → Best representative images per segment
    4. Image LLM Analysis    → Per-frame RoomKnowledge
    5. Knowledge Fusion      → Unified VKB + Candidate Attention Map
    6. Long Segment Re-analysis → Multi-space inventory for long segments

Vision Agent never generates narration, editing plans, or creative decisions.
It only perceives and constructs factual knowledge.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.agents.vision.modules.fusion import KnowledgeFusionEngine
from backend.agents.vision.modules.image_llm import ImageLLMAnalyzer
from backend.agents.vision.modules.keyframe_selector import KeyFrameSelector
from backend.agents.vision.modules.long_segment_analyzer import LongSegmentAnalyzer
from backend.agents.vision.modules.preprocessor import VideoPreprocessor
from backend.agents.vision.modules.segmenter import RoomSegmenter
from backend.core.base_agent import BaseAgent
from backend.schemas.vision_schema import VisionKnowledgeBase
from backend.services.llm.openai_provider import OpenAIProvider
from backend.state.project_state import ProjectState

logger = logging.getLogger(__name__)


class VisionAgent(BaseAgent):
    """Spatial Perception Engine for the AI Director system.

    Input: raw walkthrough video path
    Output: Vision Knowledge Base (VKB)

    The VKB is the single source of truth for all downstream agents.
    No other agent re-analyzes the video.
    """

    agent_name = "vision"
    state_key = "vision"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_provider: Any | None = None,
        work_dir: str | Path | None = None,
    ) -> None:
        """Initialize the Vision Agent with its 5 modules.

        Args:
            config: Optional configuration overrides.
            llm_provider: LLM provider instance. Defaults to OpenAI.
            work_dir: Working directory for frame extraction. Defaults to /tmp.
        """
        super().__init__(config)

        # Working directory for intermediate files
        self.work_dir = Path(work_dir or f"/tmp/ai_director/vision")

        # Module 1: Video Preprocessor (no AI)
        self.preprocessor = VideoPreprocessor(frame_sample_rate=1.0)

        # Module 2: Room Segmenter (OpenCLIP embeddings)
        segmenter_config = config.get("segmenter", {}) if config else {}
        self.segmenter = RoomSegmenter(
            distance_threshold=segmenter_config.get("distance_threshold", 0.15),
            min_segment_duration=segmenter_config.get("min_segment_duration", 3.0),
            max_segment_duration=segmenter_config.get("max_segment_duration", 15.0),
            continuous_coverage=bool(
                segmenter_config.get("continuous_coverage", True)
            ),
        )

        # Module 3: Key Frame Selector (quality scoring)
        keyframe_config = config.get("keyframe_selector", {}) if config else {}
        self.keyframe_selector = KeyFrameSelector(
            max_keyframes_per_segment=keyframe_config.get("max_per_segment", 3),
            min_sharpness=keyframe_config.get("min_sharpness", 20.0),
        )

        # Module 4: Image LLM Analyzer (vision LLM)
        self.llm_provider = llm_provider
        self.image_analyzer = ImageLLMAnalyzer(llm_provider=llm_provider)

        # Module 5: Knowledge Fusion Engine (reasoning)
        self.fusion_engine = KnowledgeFusionEngine()

        # Module 6: Long Segment Re-analysis (property space inventory)
        long_cfg = config.get("long_segment", {}) if config else {}
        self.long_segment_analyzer = LongSegmentAnalyzer(
            llm_provider=llm_provider,
            duration_threshold=float(long_cfg.get("duration_threshold", 8.0)),
            sample_count=int(long_cfg.get("sample_count", 4)),
        )

    async def run(self, state: ProjectState) -> ProjectState:
        """Execute the full Vision Agent pipeline.

        Args:
            state: Current project state with video_metadata.file_path.

        Returns:
            Updated state with Vision Knowledge Base written to vision field.
        """
        video_path = state.video_metadata.file_path
        if not video_path:
            raise ValueError("No video file path in project state")

        project_id = state.project_id or "default"
        work_dir = self.work_dir / project_id
        work_dir.mkdir(parents=True, exist_ok=True)

        frames_dir = work_dir / "frames"
        keyframes_dir = work_dir / "keyframes"

        logger.info(f"Starting Vision Agent pipeline for: {video_path}")

        # ── Module 1: Video Preprocessing ──────────────────
        logger.info("[Module 1/6] Video Preprocessing...")
        video_index = self.preprocessor.build_index(video_path)
        logger.info(
            f"  Video: {video_index.width}x{video_index.height}, "
            f"{video_index.fps:.1f}fps, {video_index.duration:.1f}s"
        )

        # Extract 1fps sample frames for segmentation
        frames = self.preprocessor.extract_frames_at_rate(
            video_path, frames_dir, sample_fps=1.0
        )
        logger.info(f"  Extracted {len(frames)} sample frames")

        # ── Module 2: Room Segmentation ────────────────────
        logger.info("[Module 2/6] Room Segmentation...")
        raw_segments = self.segmenter.segment(frames, video_index.duration)
        for seg in raw_segments:
            seg_id = getattr(seg, '__dict__', {}).get('segment_id', '?')
            logger.info(
                f"  {seg_id}: {seg.start_time:.1f}s - {seg.end_time:.1f}s "
                f"({seg.duration:.1f}s)"
            )

        # ── Module 3: Key Frame Selection ──────────────────
        logger.info("[Module 3/6] Key Frame Selection...")
        raw_segments = self.keyframe_selector.select_keyframes(
            raw_segments, frames, keyframes_dir
        )
        for seg in raw_segments:
            seg_id = getattr(seg, '__dict__', {}).get('segment_id', '?')
            logger.info(f"  {seg_id}: {len(seg.keyframes)} keyframes selected")

        # ── Module 4: Image LLM Analysis ───────────────────
        logger.info("[Module 4/6] Image LLM Analysis...")
        attention_hint = state.user_goal.prompt if state.user_goal else ""

        segments_for_analysis = []
        for seg in raw_segments:
            seg_id = getattr(seg, '__dict__', {}).get('segment_id', f'seg_?')
            segments_for_analysis.append({
                "segment_id": seg_id,
                "keyframes": seg.keyframes,
            })

        # Analyze each keyframe independently for fusion
        per_segment_analyses: list[list] = []
        for seg_info in segments_for_analysis:
            # Analyze all keyframes of this segment as a group
            # (single LLM call with multiple images)
            knowledge = await self.image_analyzer.analyze_segment(
                keyframe_paths=seg_info["keyframes"],
                attention_hint=attention_hint,
            )
            per_segment_analyses.append([knowledge])

        # ── Module 5: Knowledge Fusion ─────────────────────
        logger.info("[Module 5/6] Knowledge Fusion...")
        vkb_segments, attention_candidates = self.fusion_engine.fuse_all(
            raw_segments=raw_segments,
            analyses_per_segment=per_segment_analyses,
        )

        # ── Module 6: Long Segment Re-analysis ─────────────
        logger.info("[Module 6/6] Long Segment Re-analysis (space inventory)...")
        vkb_segments = await self.long_segment_analyzer.enrich_segments(
            vkb_segments, frames=frames
        )

        # ── Build final VKB + verified gates + primary-room onset ──
        vkb = VisionKnowledgeBase(
            project_id=state.project_id,
            agent_name=self.agent_name,
            video=video_index,
            segments=vkb_segments,
            candidate_attention=attention_candidates,
        )
        from backend.agents.vision.modules.room_onset import finalize_vision_knowledge

        vkb = finalize_vision_knowledge(vkb, frames, self.segmenter)

        logger.info(
            f"Vision Knowledge Base complete: "
            f"{len(vkb.segments)} segments, "
            f"{len(vkb.candidate_attention)} attention candidates"
        )

        for seg in vkb.segments:
            space_names = [
                f"{s.narration_name or s.display_name or s.type}"
                + (f"({s.instance_id})" if s.instance_id else "")
                for s in (seg.knowledge.spaces or [])
            ]
            logger.info(
                f"  {seg.segment_id}: {seg.knowledge.room_type} "
                f"({seg.raw.start_time:.1f}s-{seg.raw.end_time:.1f}s vis={float(seg.room_visible_start or seg.raw.start_time):.1f}s) "
                f"spaces={space_names} "
                f"[{seg.knowledge.style}, {seg.knowledge.lighting}] "
                f"selling_points={seg.knowledge.selling_points}"
            )

        return self.write_state(state, vkb.model_dump())
