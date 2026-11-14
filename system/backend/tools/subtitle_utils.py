"""Subtitle utility functions.

Provides SRT generation, subtitle rendering helpers, and
other subtitle-related utilities. Used by Rendering Agent
for deterministic subtitle operations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SubtitleEntry:
    """A single subtitle entry with timing."""

    def __init__(self, index: int, start_time: float, end_time: float, text: str) -> None:
        self.index = index
        self.start_time = start_time
        self.end_time = end_time
        self.text = text

    def to_srt(self) -> str:
        """Format this entry as an SRT block."""
        return (
            f"{self.index}\n"
            f"{self._format_timestamp(self.start_time)} --> "
            f"{self._format_timestamp(self.end_time)}\n"
            f"{self.text}\n"
        )

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as HH:MM:SS,mmm."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(
    entries: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Generate an SRT subtitle file from timing entries.

    Args:
        entries: List of dicts with 'start_time', 'end_time', 'text' keys.
        output_path: Where to save the SRT file.

    Returns:
        Path to the generated SRT file.
    """
    srt_content = ""
    for i, entry in enumerate(entries, start=1):
        subtitle = SubtitleEntry(
            index=i,
            start_time=entry.get("start_time", 0.0),
            end_time=entry.get("end_time", 0.0),
            text=entry.get("text", ""),
        )
        srt_content += subtitle.to_srt() + "\n"

    output_path.write_text(srt_content, encoding="utf-8")
    logger.info(f"Generated SRT file: {output_path} ({len(entries)} entries)")
    return output_path


def parse_srt(srt_path: Path) -> list[dict[str, Any]]:
    """Parse an SRT file into structured entries.

    Args:
        srt_path: Path to the SRT file.

    Returns:
        List of dicts with 'index', 'start_time', 'end_time', 'text'.
    """
    content = srt_path.read_text(encoding="utf-8")
    entries = []

    for block in content.strip().split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            index = int(lines[0])
            timing = lines[1].split(" --> ")
            start_time = _parse_timestamp(timing[0])
            end_time = _parse_timestamp(timing[1])
            text = "\n".join(lines[2:])
            entries.append({
                "index": index,
                "start_time": start_time,
                "end_time": end_time,
                "text": text,
            })

    return entries


def _parse_timestamp(timestamp: str) -> float:
    """Parse an SRT timestamp (HH:MM:SS,mmm) to seconds."""
    timestamp = timestamp.strip()
    time_part, millis = timestamp.split(",")
    hours, minutes, seconds = time_part.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000
