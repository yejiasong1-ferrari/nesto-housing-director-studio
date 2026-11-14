"""FFmpeg utility functions.

Provides command builders and helpers for common FFmpeg operations.
These are deterministic utilities used by the Rendering Agent.
They never perform reasoning.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def build_clip_command(
    input_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    codec: str = "libx264",
    audio_codec: str = "aac",
) -> list[str]:
    """Build an FFmpeg command to clip a video segment.

    Args:
        input_path: Source video file.
        output_path: Destination file.
        start_time: Start time in seconds.
        end_time: End time in seconds.
        codec: Video codec.
        audio_codec: Audio codec.

    Returns:
        FFmpeg command as a list of strings.
    """
    return [
        "ffmpeg",
        "-i", str(input_path),
        "-ss", str(start_time),
        "-to", str(end_time),
        "-c:v", codec,
        "-c:a", audio_codec,
        "-y",
        str(output_path),
    ]


def build_slow_motion_command(
    input_path: Path,
    output_path: Path,
    speed_factor: float = 0.5,
    codec: str = "libx264",
) -> list[str]:
    """Build an FFmpeg command for slow motion effect.

    Args:
        input_path: Source video file.
        output_path: Destination file.
        speed_factor: Playback speed (0.5 = half speed).
        codec: Video codec.

    Returns:
        FFmpeg command as a list of strings.
    """
    pts_factor = 1.0 / speed_factor
    return [
        "ffmpeg",
        "-i", str(input_path),
        "-filter:v", f"setpts={pts_factor}*PTS",
        "-filter:a", f"atempo={speed_factor}",
        "-c:v", codec,
        "-y",
        str(output_path),
    ]


def build_concat_command(
    input_files: list[Path],
    output_path: Path,
) -> list[str]:
    """Build an FFmpeg command to concatenate multiple video files.

    Args:
        input_files: List of video files to concatenate.
        output_path: Destination file.

    Returns:
        FFmpeg command as a list of strings.
    """
    # Uses concat demuxer - requires a file list
    return [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", "filelist.txt",
        "-c", "copy",
        "-y",
        str(output_path),
    ]


def build_add_audio_command(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    codec: str = "libx264",
    audio_codec: str = "aac",
) -> list[str]:
    """Build an FFmpeg command to add audio to a video.

    Args:
        video_path: Source video file.
        audio_path: Audio file to add.
        output_path: Destination file.
        codec: Video codec.
        audio_codec: Audio codec.

    Returns:
        FFmpeg command as a list of strings.
    """
    return [
        "ffmpeg",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", codec,
        "-c:a", audio_codec,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        "-y",
        str(output_path),
    ]


def run_ffmpeg(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """Execute an FFmpeg command.

    Args:
        command: FFmpeg command as a list of strings.
        timeout: Maximum execution time in seconds.

    Returns:
        CompletedProcess result.
    """
    logger.info(f"Running FFmpeg: {' '.join(command)}")
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
