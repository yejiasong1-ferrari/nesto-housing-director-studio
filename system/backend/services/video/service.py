"""Video processing service.

Provides video metadata extraction, frame extraction, and
other video processing utilities. Wraps FFmpeg and OpenCV.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class VideoInfo(BaseModel):
    """Extracted video metadata."""

    file_path: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    file_size: int = 0
    frame_count: int = 0


class VideoService:
    """Service for video processing operations.

    Wraps FFmpeg and OpenCV for video metadata extraction,
    frame extraction, and format conversion.
    """

    async def get_video_info(self, video_path: Path) -> VideoInfo:
        """Extract metadata from a video file.

        TODO: Implement using FFmpeg/ffprobe.
        """
        logger.info(f"Extracting video info: {video_path}")
        return VideoInfo(file_path=str(video_path))

    async def extract_frame(self, video_path: Path, timestamp: float, output_path: Path) -> Path:
        """Extract a single frame at the given timestamp.

        TODO: Implement using FFmpeg.
        """
        logger.info(f"Extracting frame at {timestamp}s from {video_path}")
        return output_path

    async def extract_frames(
        self, video_path: Path, interval: float = 1.0, output_dir: Path | None = None
    ) -> list[Path]:
        """Extract frames at regular intervals.

        TODO: Implement using FFmpeg or OpenCV.
        """
        logger.info(f"Extracting frames every {interval}s from {video_path}")
        return []

    async def get_duration(self, video_path: Path) -> float:
        """Get video duration in seconds.

        TODO: Implement using FFmpeg.
        """
        return 0.0
