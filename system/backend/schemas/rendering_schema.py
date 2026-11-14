"""Rendering Agent schema models.

Input configuration and output of the Rendering Agent.
The Rendering Agent is purely deterministic -- it never calls
LLMs or performs reasoning. It only executes Timeline +
Editing Strategy using FFmpeg/MoviePy/OpenCV.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


class RenderConfig(BaseModel):
    """Configuration for the rendering process."""

    output_format: str = "mp4"
    output_resolution: tuple[int, int] = (1920, 1080)
    output_fps: float = 30.0
    codec: str = "libx264"
    audio_codec: str = "aac"
    subtitle_style: dict[str, Any] = Field(default_factory=lambda: {
        "font_size": 24,
        "font_color": "white",
        "background_color": "black",
        "position": "bottom",
    })


class RenderOutput(VersionedBaseModel):
    """Complete output of the Rendering Agent.

    Contains the final rendered video path and metadata.
    Rendering never infers new information -- it only
    executes the Timeline and Editing Strategy.
    """

    agent_name: str = "rendering"
    output_path: str = ""
    duration: float = 0.0
    file_size: int = 0
    resolution: tuple[int, int] = (1920, 1080)
    fps: float = 30.0
    has_subtitles: bool = False
    has_voiceover: bool = False
