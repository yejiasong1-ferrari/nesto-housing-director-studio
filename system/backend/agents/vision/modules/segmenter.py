"""Module 2: Room Segmentation (Spatial Boundary Detection).

Finds spatial boundaries in the walkthrough video by computing
image embeddings and detecting significant visual changes.

This module does NOT identify rooms (that's the LLM's job).
It only finds where one space transitions to another.

Why not YOLO?
- YOLO answers: "Here is a Chair, Table, TV"
- We need: "Here is a Living Room"
- Room Segmentation is based on spatial change, not object detection.

Uses OpenCLIP for semantic image embeddings and cosine distance
to detect scene transitions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import torch

from backend.schemas.vision_schema import RawSegment

logger = logging.getLogger(__name__)


class RoomSegmenter:
    """Detects spatial boundaries in walkthrough video using embedding distance.

    Pipeline:
    1. Load pre-extracted sample frames (1 fps from preprocessor)
    2. Compute OpenCLIP embeddings for each frame
    3. Calculate cosine distance between consecutive frames
    4. Detect boundaries where distance exceeds threshold
    5. Merge short segments and produce raw temporal segments
    """

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "openai",
        distance_threshold: float = 0.15,
        min_segment_duration: float = 3.0,
        max_segment_duration: float = 20.0,
        transition_duration: float = 1.5,
        continuous_coverage: bool = True,
        device: str | None = None,
    ) -> None:
        """Initialize the room segmenter.

        Args:
            model_name: OpenCLIP model name.
            pretrained: Pretrained weights identifier.
            distance_threshold: Cosine distance threshold for boundary detection.
            min_segment_duration: Minimum duration in seconds for a valid segment.
            max_segment_duration: Maximum duration before splitting at the
                highest-distance point within the segment.
            transition_duration: Duration to exclude at each boundary (legacy;
                ignored when continuous_coverage is True).
            continuous_coverage: If True, seal segments so they tile
                [0, total_duration] with no dropped head/tail/gaps.
            device: Compute device (auto-detected if None).
        """
        self.model_name = model_name
        self.pretrained = pretrained
        self.distance_threshold = distance_threshold
        self.min_segment_duration = min_segment_duration
        self.max_segment_duration = max_segment_duration
        self.transition_duration = transition_duration
        self.continuous_coverage = continuous_coverage
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self._model = None
        self._preprocess = None
        self._tokenizer = None

    def _load_model(self) -> None:
        """Lazy-load the OpenCLIP model."""
        if self._model is not None:
            return

        import open_clip

        logger.info(f"Loading OpenCLIP model: {self.model_name} ({self.pretrained})")
        model, _, self._preprocess = open_clip.create_model_and_transforms(
            self.model_name, pretrained=self.pretrained
        )
        self._tokenizer = open_clip.get_tokenizer(self.model_name)
        model = model.to(self.device)
        model.eval()
        self._model = model
        logger.info("OpenCLIP model loaded successfully")

    @torch.no_grad()
    def compute_embedding(self, image_path: str | Path) -> torch.Tensor:
        """Compute normalized CLIP embedding for a single image.

        Args:
            image_path: Path to the image file.

        Returns:
            Normalized embedding tensor of shape (1, embed_dim).
        """
        from PIL import Image

        self._load_model()

        img = Image.open(image_path).convert("RGB")
        img_tensor = self._preprocess(img).unsqueeze(0).to(self.device)
        embedding = self._model.encode_image(img_tensor)
        embedding = embedding / embedding.norm(dim=-1, keepdim=True)
        return embedding

    @torch.no_grad()
    def encode_text(self, text: str) -> torch.Tensor:
        """Normalized CLIP text embedding (cached per instance)."""
        self._load_model()
        cache = getattr(self, "_text_cache", None)
        if cache is None:
            self._text_cache = {}
            cache = self._text_cache
        if text in cache:
            return cache[text]
        tokens = self._tokenizer([text]).to(self.device)
        feat = self._model.encode_text(tokens)
        feat = feat / feat.norm(dim=-1, keepdim=True)
        cache[text] = feat
        return feat

    def score_image_text(self, image_embedding: torch.Tensor, text: str) -> float:
        """Cosine similarity between an image embedding and a text prompt."""
        text_emb = self.encode_text(text)
        return float((image_embedding @ text_emb.T).squeeze().item())

    def compute_distances(
        self, frames: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Compute pairwise cosine distances between consecutive frames.

        Args:
            frames: List of frame dicts with 'frame_path' and 'timestamp'.

        Returns:
            List of dicts with timestamp, distance to previous frame,
            and embedding tensor.
        """
        if not frames:
            return []

        logger.info(f"Computing embeddings for {len(frames)} frames...")
        embeddings = []
        for i, frame in enumerate(frames):
            emb = self.compute_embedding(frame["frame_path"])
            embeddings.append(emb)
            if (i + 1) % 50 == 0:
                logger.info(f"  Embedded {i + 1}/{len(frames)} frames")

        distances = []
        for i in range(len(frames)):
            if i == 0:
                distances.append({
                    "timestamp": frames[i]["timestamp"],
                    "frame_idx": frames[i].get("frame_idx", i),
                    "distance": 0.0,
                    "embedding": embeddings[i],
                })
            else:
                cos_dist = 1.0 - torch.nn.functional.cosine_similarity(
                    embeddings[i], embeddings[i - 1]
                ).item()
                distances.append({
                    "timestamp": frames[i]["timestamp"],
                    "frame_idx": frames[i].get("frame_idx", i),
                    "distance": cos_dist,
                    "embedding": embeddings[i],
                })

        return distances

    def detect_boundaries(
        self, distances: list[dict[str, Any]]
    ) -> list[int]:
        """Detect segment boundary indices based on embedding distance spikes.

        Args:
            distances: Output of compute_distances().

        Returns:
            List of indices where new segments begin.
        """
        if not distances:
            return []

        # Find frames where distance exceeds threshold
        boundaries = [0]  # First frame is always a boundary
        for i, d in enumerate(distances):
            if i == 0:
                continue
            if d["distance"] > self.distance_threshold:
                boundaries.append(i)
                logger.debug(
                    f"  Boundary at t={d['timestamp']:.1f}s "
                    f"(distance={d['distance']:.4f})"
                )

        logger.info(f"Detected {len(boundaries)} spatial boundaries")
        return boundaries

    def build_segments(
        self,
        distances: list[dict[str, Any]],
        boundaries: list[int],
        total_duration: float,
    ) -> list[RawSegment]:
        """Build raw temporal segments from detected boundaries.

        Args:
            distances: Frame distance data with timestamps.
            boundaries: Indices where boundaries occur.
            total_duration: Total video duration in seconds.

        Returns:
            List of RawSegment objects with timestamps.
        """
        segments: list[RawSegment] = []
        # Short leading fragments accumulate until a keepable segment exists
        pending_start: float | None = None

        for seg_idx in range(len(boundaries)):
            start_idx = boundaries[seg_idx]
            end_idx = (
                boundaries[seg_idx + 1]
                if seg_idx + 1 < len(boundaries)
                else len(distances)
            )

            start_time = distances[start_idx]["timestamp"]
            end_time = (
                distances[end_idx - 1]["timestamp"]
                if end_idx > start_idx
                else start_time
            )

            # Include frames up to the next boundary (no intentional gap)
            if seg_idx < len(boundaries) - 1:
                next_boundary_t = distances[boundaries[seg_idx + 1]]["timestamp"]
                end_time = max(end_time, next_boundary_t)
            else:
                end_time = max(end_time, float(total_duration))

            if pending_start is not None:
                start_time = pending_start

            duration = end_time - start_time

            # Short segments: merge into previous, or hold start for next
            if duration < self.min_segment_duration:
                if segments:
                    segments[-1].end_time = end_time
                    segments[-1].duration = end_time - segments[-1].start_time
                    pending_start = None
                    logger.debug(
                        "  Merged short segment at %.1fs into previous",
                        start_time,
                    )
                else:
                    pending_start = start_time
                    logger.debug(
                        "  Holding short leading fragment [%.1f-%.1f]",
                        start_time,
                        end_time,
                    )
                continue

            pending_start = None
            segment = RawSegment(
                start_time=round(start_time, 2),
                end_time=round(end_time, 2),
                duration=round(duration, 2),
                keyframes=[],  # Filled by KeyFrameSelector
            )
            segments.append(segment)

        # Entire video was short fragments — keep one full-span segment
        if not segments and total_duration > 0:
            segments.append(
                RawSegment(
                    start_time=0.0,
                    end_time=round(float(total_duration), 2),
                    duration=round(float(total_duration), 2),
                    keyframes=[],
                )
            )

        # Assign segment IDs
        for i, seg in enumerate(segments):
            seg.__dict__["segment_id"] = f"seg_{i + 1:02d}"

        # Split overly long segments at their highest-distance point
        segments = self._split_long_segments(segments, distances)

        if self.continuous_coverage:
            segments = self._seal_continuous_coverage(segments, total_duration)

        logger.info(f"Built {len(segments)} raw segments")
        return segments

    def _seal_continuous_coverage(
        self,
        segments: list[RawSegment],
        total_duration: float,
    ) -> list[RawSegment]:
        """Ensure segments tile [0, total_duration] with no gaps or overlaps."""
        if not segments:
            return segments

        total = max(0.0, float(total_duration))
        segments[0].start_time = 0.0

        for i in range(len(segments) - 1):
            # Absorb any gap into the earlier segment (preserve later room start)
            next_start = float(segments[i + 1].start_time)
            segments[i].end_time = round(next_start, 2)
            segments[i].duration = round(
                segments[i].end_time - segments[i].start_time, 2
            )

        segments[-1].end_time = round(total, 2)
        segments[-1].duration = round(
            segments[-1].end_time - segments[-1].start_time, 2
        )

        # Drop zero/negative spans created by seal edge cases
        sealed = [s for s in segments if s.duration > 0.05]
        for i, seg in enumerate(sealed):
            seg.__dict__["segment_id"] = f"seg_{i + 1:02d}"

        if sealed:
            logger.info(
                "Continuous coverage sealed: %.2fs → %.2fs across %d segments",
                sealed[0].start_time,
                sealed[-1].end_time,
                len(sealed),
            )
        return sealed

    def _split_long_segments(
        self,
        segments: list[RawSegment],
        distances: list[dict[str, Any]],
    ) -> list[RawSegment]:
        """Split segments that exceed max_segment_duration.

        Finds the frame with the highest distance within the segment
        and splits there. Uses iterative approach to avoid deep recursion.

        Args:
            segments: List of RawSegment objects.
            distances: Frame distance data.

        Returns:
            Updated list with long segments split.
        """
        result = list(segments)

        changed = True
        max_iterations = 20
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1
            new_result = []

            for seg in result:
                if seg.duration <= self.max_segment_duration:
                    new_result.append(seg)
                    continue

                # Find frames within this segment
                seg_frames = [
                    d for d in distances
                    if seg.start_time <= d["timestamp"] <= seg.end_time and d["distance"] > 0
                ]

                if not seg_frames:
                    new_result.append(seg)
                    continue

                # Find the point with maximum distance
                # Skip the first frame (it's at the boundary) and look for
                # the highest internal distance
                internal_frames = [
                    d for d in seg_frames
                    if d["timestamp"] > seg.start_time + 1.0
                    and d["timestamp"] < seg.end_time - 1.0
                ]

                if not internal_frames:
                    new_result.append(seg)
                    continue

                max_frame = max(internal_frames, key=lambda d: d["distance"])
                split_time = max_frame["timestamp"]

                # Don't split too close to boundaries (need meaningful segments)
                min_split_offset = 2.0
                if (split_time - seg.start_time < min_split_offset or
                    seg.end_time - split_time < min_split_offset):
                    new_result.append(seg)
                    continue

                logger.info(
                    f"  Splitting {getattr(seg, '__dict__', {}).get('segment_id', '?')} "
                    f"({seg.duration:.1f}s) at t={split_time:.1f}s "
                    f"(distance={max_frame['distance']:.4f})"
                )

                left = RawSegment(
                    start_time=seg.start_time,
                    end_time=round(split_time, 2),
                    duration=round(split_time - seg.start_time, 2),
                    keyframes=[],
                )
                right = RawSegment(
                    start_time=round(split_time, 2),
                    end_time=seg.end_time,
                    duration=round(seg.end_time - split_time, 2),
                    keyframes=[],
                )

                new_result.extend([left, right])
                changed = True

            result = new_result

        # Re-assign segment IDs
        for i, seg in enumerate(result):
            seg.__dict__["segment_id"] = f"seg_{i + 1:02d}"

        return result

    def segment(
        self,
        frames: list[dict[str, Any]],
        total_duration: float,
    ) -> list[RawSegment]:
        """Full segmentation pipeline.

        Args:
            frames: Pre-extracted sample frames from VideoPreprocessor.
            total_duration: Total video duration in seconds.

        Returns:
            List of RawSegment with temporal boundaries.
        """
        logger.info("Starting room segmentation...")

        distances = self.compute_distances(frames)
        boundaries = self.detect_boundaries(distances)
        segments = self.build_segments(distances, boundaries, total_duration)

        logger.info(
            f"Segmentation complete: {len(segments)} segments from "
            f"{total_duration:.1f}s video"
        )
        return segments
