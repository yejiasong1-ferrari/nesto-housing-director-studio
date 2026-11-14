"""Rendering Agent schema.

Rendering Agent is a deterministic execution engine.
It converts timeline + editing plan into a final MP4.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


class RenderSegmentResult(BaseModel):
    """Result of rendering one timeline segment."""

    segment_id: str = ""
    clip_path: str = ""
    duration: float = 0.0
    effects_applied: list[str] = Field(default_factory=list)
    audio_mixed: bool = False
    subtitle_burned: bool = False


class StudioTimingSegment(BaseModel):
    """Maps MP4 time ↔ non-overlapping Studio timeline for playhead sync."""

    id: str = ""
    layout_start: float = 0.0
    layout_duration: float = 0.0
    video_start: float = 0.0
    video_duration: float = 0.0
    narration_at: float = 0.0
    audio_offset: float = 0.0
    audio_duration: float = 0.0


class RenderResult(VersionedBaseModel):
    """Output of the Rendering Agent."""

    agent_name: str = "rendering"
    status: str = "success"   # success | failed
    output_path: str = ""
    duration: float = 0.0
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    file_size_mb: float = 0.0
    segments: list[RenderSegmentResult] = Field(default_factory=list)
    # Fixed BGM mix metadata (from workflow audio_config)
    bgm_mixed: bool = False
    bgm_path: str = ""
    bgm_volume_db: float = -18.0
    # Per-segment timing for Director Studio playhead ↔ audio alignment
    studio_timing: list[StudioTimingSegment] = Field(default_factory=list)
    error: str = ""
