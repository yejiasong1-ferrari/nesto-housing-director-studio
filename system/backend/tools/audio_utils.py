"""Audio utility functions.

Provides audio duration measurement, waveform generation,
and other audio processing helpers. Used by Voice Agent
and Rendering Agent.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_audio_duration(audio_path: Path) -> float:
    """Get the duration of an audio file in seconds.

    Args:
        audio_path: Path to the audio file.

    Returns:
        Duration in seconds, or 0.0 if unable to determine.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(audio_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0.0))
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to get audio duration: {e}")

    return 0.0


def get_audio_info(audio_path: Path) -> dict[str, Any]:
    """Extract audio file metadata using ffprobe.

    Args:
        audio_path: Path to the audio file.

    Returns:
        Dictionary with audio metadata.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(audio_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.error(f"Failed to get audio info: {e}")

    return {}


def concatenate_audio_files(
    audio_paths: list[Path],
    output_path: Path,
) -> bool:
    """Concatenate multiple audio files into one.

    Args:
        audio_paths: Ordered list of audio files to concatenate.
        output_path: Destination file.

    Returns:
        True if concatenation succeeded.
    """
    filter_inputs = "".join(
        f"[{i}:a]" for i in range(len(audio_paths))
    )
    cmd = ["ffmpeg"]
    for path in audio_paths:
        cmd.extend(["-i", str(path)])
    cmd.extend([
        "-filter_complex", f"{filter_inputs}concat=n={len(audio_paths)}:v=0:a=1[out]",
        "-map", "[out]",
        "-y",
        str(output_path),
    ])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("Audio concatenation timed out")
        return False
