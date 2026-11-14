"""Video utility functions.

Provides video metadata extraction, frame extraction, and
other video processing helpers. Used by Vision Agent and
Rendering Agent for deterministic video operations.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_video_metadata(video_path: Path) -> dict[str, Any]:
    """Extract video metadata using ffprobe.

    Args:
        video_path: Path to the video file.

    Returns:
        Dictionary with video metadata.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.error(f"Failed to get video metadata: {e}")

    return {}


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> bool:
    """Extract a single frame from a video at a given timestamp.

    Args:
        video_path: Source video file.
        timestamp: Time in seconds.
        output_path: Where to save the frame image.

    Returns:
        True if extraction succeeded.
    """
    cmd = [
        "ffmpeg",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-frames:v", "1",
        "-y",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"Frame extraction timed out: {video_path}")
        return False


def get_video_duration(video_path: Path) -> float:
    """Get the duration of a video file in seconds.

    Args:
        video_path: Path to the video file.

    Returns:
        Duration in seconds, or 0.0 if unable to determine.
    """
    metadata = get_video_metadata(video_path)
    try:
        return float(metadata.get("format", {}).get("duration", 0.0))
    except (ValueError, TypeError):
        return 0.0
