"""Timeline Agent schema — Narrative Temporal Director output.

The Timeline Agent is the first layer that resolves:
  "When should each sentence be spoken? How long should each scene run?
   Should two segments be merged? Where are the narrative pauses?"

It synthesises Vision + Planner + Script + Voice into a single executable
cinematic time structure consumed by Editing Strategy Agent.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


# ── Duration strategy enum ────────────────────────────────────────────────────

class DurationAdjustmentStrategy(str, Enum):
    SLOW_MOTION = "slow_motion"       # extend video by slowing playback
    FREEZE_FRAME = "freeze_frame"     # hold last frame to fill remaining time
    ZOOM_EXTEND = "zoom_extend"       # slow cinematic zoom fills time
    INSERT_VISUAL_ACCENT = "insert_visual_accent"  # cutaway / still insert
    TRIM_VIDEO = "trim_video"         # video longer than audio — keep full span (do not cut)
    FLAG_REWRITE = "flag_rewrite"     # audio >> video; low importance → rewrite
    NO_ADJUSTMENT = "no_adjustment"   # within tolerance


# ── Sub-models ────────────────────────────────────────────────────────────────

class SourceTiming(BaseModel):
    """Original video timing from Vision Agent (immutable)."""
    video_start: float = 0.0
    video_end: float = 0.0
    video_duration: float = 0.0


class NarrationInfo(BaseModel):
    """Narration text + actual audio data from Script + Voice agents."""
    text: str = ""
    tts_text: str = ""
    audio_path: str = ""
    audio_duration: float = 0.0    # actual measured duration (Voice Execution)
    estimated_duration: float = 0.0  # Voice Agent estimate
    emotion: str = "neutral"
    delivery_speed: float = 1.0


class DurationDecision(BaseModel):
    """Decision about how to reconcile audio vs video duration."""
    strategy: DurationAdjustmentStrategy = DurationAdjustmentStrategy.NO_ADJUSTMENT
    audio_duration: float = 0.0
    video_duration: float = 0.0
    delta: float = 0.0              # audio - video; positive = audio longer
    editing_window: float = 0.0     # final allocated duration for this segment
    extension_factor: float = 1.0   # for slow_motion: playback rate
    needs_script_rewrite: bool = False
    # How much spoken audio can fit after the room is visible.
    # Used by rewrite passes so delayed entry shortens the line instead of
    # moving narration back into the hallway.
    target_audio_duration: float = 0.0


class VisualPlan(BaseModel):
    """Cinematic direction for this segment."""
    story_phase: str = ""   # opening_hook / discovery / emotional_center / etc.
    pace: str = "medium"    # slow | medium | fast
    focus_elements: list[str] = Field(default_factory=list)
    cinematic_intent: str = ""


class TransitionPlan(BaseModel):
    """How this segment connects to the next."""
    to_segment_id: str = ""
    type: str = "cut"             # cut | soft_pan | camera_pan | dissolve | quick_cut | fade
    duration: float = 0.3
    reason: str = ""


class MergeInfo(BaseModel):
    """Records whether this segment was the result of a merge decision."""
    decision: str = "KEEP"        # KEEP | MERGED_HEAD | ABSORBED
    merged_with: list[str] = Field(default_factory=list)
    merge_score: float = 0.0
    merge_reason: str = ""


# ── Main segment model ────────────────────────────────────────────────────────

class TimelineSegment(BaseModel):
    """One planned segment in the final cinematic timeline.

    May represent a single original scene or several merged scenes.
    Carries everything Editing Strategy Agent needs to execute.
    """

    id: str = ""                  # "tl_001", "tl_002+003" if merged
    source_ids: list[str] = Field(default_factory=list)  # original VKB segment ids
    room_type: str = ""
    role: str = ""                # HERO | SUPPORT | TRANSITION
    arc_stage: str = ""
    importance: float = 0.0

    source: SourceTiming = Field(default_factory=SourceTiming)
    narration: NarrationInfo = Field(default_factory=NarrationInfo)
    visual_plan: VisualPlan = Field(default_factory=VisualPlan)
    duration_decision: DurationDecision = Field(default_factory=DurationDecision)
    transition: TransitionPlan = Field(default_factory=TransitionPlan)
    merge: MergeInfo = Field(default_factory=MergeInfo)

    # Final position in the assembled timeline
    timeline_start: float = 0.0
    timeline_end: float = 0.0
    # Seconds after this clip's picture start when TTS may begin.
    # Default from Vision room_visible_start; Studio may still nudge it.
    audio_offset: float = 0.0
    room_visible_end: float = 0.0


# ── Validation ────────────────────────────────────────────────────────────────

class TimelineValidation(BaseModel):
    is_valid: bool = True
    issues: list[str] = Field(default_factory=list)
    must_show_coverage: dict[str, bool] = Field(default_factory=dict)
    duplicate_warnings: list[str] = Field(default_factory=list)
    total_duration_check: bool = True


# ── Top-level output ──────────────────────────────────────────────────────────

class TimelineOutput(VersionedBaseModel):
    """Complete output of the Timeline Agent (Narrative Temporal Director)."""

    agent_name: str = "timeline"
    total_duration: float = 0.0
    segment_count: int = 0
    merge_count: int = 0
    hero_segment_ids: list[str] = Field(default_factory=list)
    segments: list[TimelineSegment] = Field(default_factory=list)
    validation: TimelineValidation = Field(default_factory=TimelineValidation)


# ── Backward-compat aliases (old stub consumers) ──────────────────────────────

class Timeline(TimelineOutput):
    """Alias for backward compatibility."""

    # old stub fields
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    overlaps: list[dict[str, Any]] = Field(default_factory=list)
