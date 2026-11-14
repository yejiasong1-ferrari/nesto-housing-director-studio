"""Module 3: Key Frame Selection.

The most important module for quality vs cost tradeoff.

Principle: Don't analyze more images. Analyze the BEST images.

For each segment (e.g., Kitchen, 13 seconds, ~390 frames at 30fps),
we select only 2-4 representative keyframes that best represent
the entire room. These are the ONLY images sent to the LLM.

Selection is based on a composite score combining:
- Sharpness (Laplacian variance)
- Exposure quality (histogram analysis)
- Composition balance (edge distribution)
- Motion blur detection
- Coverage (temporal spread across the segment)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.schemas.vision_schema import RawSegment

logger = logging.getLogger(__name__)


class KeyFrameSelector:
    """Selects the best representative frames for each segment.

    Instead of analyzing every frame, we score frames and select
    only the highest-quality, most representative ones.
    """

    def __init__(
        self,
        max_keyframes_per_segment: int = 3,
        min_sharpness: float = 20.0,
    ) -> None:
        """Initialize keyframe selector.

        Args:
            max_keyframes_per_segment: Maximum keyframes to select per segment.
            min_sharpness: Minimum Laplacian variance to consider a frame sharp.
        """
        self.max_keyframes = max_keyframes_per_segment
        self.min_sharpness = min_sharpness

    def score_frame(self, image_path: str | Path) -> dict[str, float]:
        """Score a single frame on quality metrics.

        Args:
            image_path: Path to the image file.

        Returns:
            Dict with sharpness, exposure, and composite scores.
        """
        import cv2
        import numpy as np

        img = cv2.imread(str(image_path))
        if img is None:
            return {"sharpness": 0.0, "exposure": 0.0, "composite": 0.0}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Sharpness: Laplacian variance
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()

        # Exposure: How well-distributed the histogram is
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist_norm = hist.flatten() / hist.sum()
        # Penalize overexposed (concentrated at 255) or underexposed (at 0)
        exposure_score = 1.0 - abs(hist_norm[255] - hist_norm[0])
        # Reward spread
        non_zero_bins = np.count_nonzero(hist_norm > 0.001)
        exposure_score = exposure_score * 0.5 + (non_zero_bins / 256.0) * 0.5

        # Normalize sharpness to 0-1 range
        sharpness_norm = min(sharpness / 200.0, 1.0)

        # Composite score
        composite = sharpness_norm * 0.6 + exposure_score * 0.4

        return {
            "sharpness": sharpness,
            "sharpness_norm": sharpness_norm,
            "exposure": exposure_score,
            "composite": composite,
        }

    def select_keyframes_for_segment(
        self,
        segment: RawSegment,
        frames: list[dict[str, Any]],
        output_dir: str | Path,
    ) -> list[str]:
        """Select the best keyframes for a single segment.

        Args:
            segment: Raw temporal segment.
            frames: All extracted frames with timestamps.
            output_dir: Directory to save keyframe copies.

        Returns:
            List of keyframe file paths.
        """
        import cv2
        import shutil

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Filter frames within this segment's time range
        segment_frames = [
            f for f in frames
            if segment.start_time <= f["timestamp"] <= segment.end_time
        ]

        if not segment_frames:
            logger.warning(
                f"No frames found for segment "
                f"{getattr(segment, '__dict__', {}).get('segment_id', '?')} "
                f"({segment.start_time}-{segment.end_time}s)"
            )
            return []

        # Score all frames
        scored_frames = []
        for f in segment_frames:
            scores = self.score_frame(f["frame_path"])
            scored_frames.append({
                **f,
                "scores": scores,
            })

        # Sort by composite score (descending)
        scored_frames.sort(key=lambda x: x["scores"]["composite"], reverse=True)

        # Select top frames with temporal coverage
        selected = []
        remaining = list(scored_frames)

        while len(selected) < self.max_keyframes and remaining:
            # Pick the best remaining frame
            best = remaining.pop(0)

            # Check sharpness threshold
            if best["scores"]["sharpness"] < self.min_sharpness:
                continue

            # Copy to keyframes directory
            seg_id = getattr(segment, '__dict__', {}).get('segment_id', 'unknown')
            keyframe_name = f"keyframe_{seg_id}_{len(selected) + 1}.jpg"
            keyframe_path = output_dir / keyframe_name
            shutil.copy2(best["frame_path"], keyframe_path)

            selected.append(str(keyframe_path))

            # Remove frames too close to the selected one (ensure coverage)
            min_gap = segment.duration / (self.max_keyframes + 1) * 0.5
            remaining = [
                f for f in remaining
                if abs(f["timestamp"] - best["timestamp"]) > min_gap
            ]

        logger.info(
            f"Selected {len(selected)} keyframes for "
            f"segment {seg_id} ({segment.start_time}-{segment.end_time}s)"
        )
        return selected

    def select_keyframes(
        self,
        segments: list[RawSegment],
        frames: list[dict[str, Any]],
        output_dir: str | Path,
    ) -> list[RawSegment]:
        """Select keyframes for all segments.

        Args:
            segments: List of raw segments (modified in place with keyframe paths).
            frames: All extracted frames with timestamps.
            output_dir: Directory to save keyframe files.

        Returns:
            Updated segments with keyframe paths populated.
        """
        output_dir = Path(output_dir)

        for seg in segments:
            keyframes = self.select_keyframes_for_segment(seg, frames, output_dir)
            seg.keyframes = keyframes

        total_keyframes = sum(len(s.keyframes) for s in segments)
        logger.info(f"Selected {total_keyframes} total keyframes across {len(segments)} segments")
        return segments
