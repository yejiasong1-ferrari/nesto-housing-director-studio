"""Editing Strategy Agent schema.

Editing Agent transforms timeline segments into abstract cinematic
strategies. It decides HOW to present — never cuts video, never changes
time, never generates media.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


# ---------------------------------------------------------------------------
# LLM director decision (cognitive output)
# ---------------------------------------------------------------------------

class FocusElement(BaseModel):
    """Ordered visual focus target from the cinematic reasoner."""

    element: str = ""
    reason: str = ""
    priority: int = 1


class DirectorDecision(BaseModel):
    """LLM cinematic reasoning for one segment (cognitive only)."""

    visual_goal: str = ""
    focus_order: list[FocusElement] = Field(default_factory=list)
    recommended_style: list[str] = Field(default_factory=list)
    # e.g. wide_shot | slow_push | minimal_text | soft_transition
    pacing_hint: str = ""          # slow | medium | fast
    transition_hint: str = ""      # soft_pan | dissolve | cut | fade
    subtitle_hint: str = ""        # premium | minimal | none
    reason: str = ""


# ---------------------------------------------------------------------------
# Deterministic strategy layers (rule planners)
# ---------------------------------------------------------------------------

class VisualOperation(BaseModel):
    """One executable visual directive for Rendering."""

    type: str = "clean_cut"
    # slow_zoom | zoom | slow_motion | freeze_frame | ken_burns | clean_cut | crop
    target: str = ""
    strength: float = 0.5          # 0..1 normalized intensity
    parameters: dict = Field(default_factory=dict)
    reason: str = ""


class VisualStrategyBlock(BaseModel):
    """Visual storytelling block for one segment."""

    focus: list[str] = Field(default_factory=list)
    operations: list[VisualOperation] = Field(default_factory=list)


class MotionProfile(BaseModel):
    """How motion should feel within a fixed timeline window."""

    style: str = "normal"          # cinematic | normal | brisk | fade_out
    speed: float = 1.0             # relative motion intensity 0.5..1.2
    camera_change_frequency: str = "normal"  # low | normal | high
    hold_time: str = "normal"      # short | normal | long


class TransitionStrategy(BaseModel):
    type: str = "cut"
    duration: float = 0.0          # capped by validator (<= 2.0s)
    reason: str = ""


class SubtitleStrategy(BaseModel):
    enabled: bool = True
    style: str = "minimal"         # premium | minimal | none
    position: str = "bottom"
    animation: str = "fade"        # fade | none
    highlight: list[str] = Field(default_factory=list)
    font_size: int = 30
    color: str = "white"
    bg_opacity: float = 0.55
    max_chars_per_line: int = 40


class AudioStrategy(BaseModel):
    """Sound-layer design (not music generation)."""

    background_music: bool = False
    music_volume: float = 0.0
    voice_ducking: bool = True
    transition_fade: bool = True
    mood: str = ""


# ---------------------------------------------------------------------------
# Backward-compatible aliases used by Rendering
# ---------------------------------------------------------------------------

class VisualStrategy(BaseModel):
    """Legacy single-strategy view — derived from VisualOperation."""

    type: str = "clean_cut"
    parameters: dict = Field(default_factory=dict)
    reason: str = ""


class SubtitleStyle(BaseModel):
    """Legacy subtitle view — mirrors SubtitleStrategy fields Rendering uses."""

    enabled: bool = True
    font_size: int = 30
    color: str = "white"
    bg_opacity: float = 0.55
    position: str = "bottom"
    animation: str = "fade"
    highlight_words: list[str] = Field(default_factory=list)
    max_chars_per_line: int = 40


class MusicCue(BaseModel):
    mood: str = ""
    energy: float = 0.5
    volume: float = 0.15


# ---------------------------------------------------------------------------
# Segment + plan
# ---------------------------------------------------------------------------

class EditingSegmentPlan(BaseModel):
    """Complete cinematic strategy for one timeline segment.

    MUST NOT alter video_start/end, merge segments, or rewrite narration.
    """

    segment_id: str = ""
    source_ids: list[str] = Field(default_factory=list)
    room_type: str = ""
    role: str = ""

    # New director-level blocks
    director_decision: DirectorDecision = Field(default_factory=DirectorDecision)
    visual_strategy: VisualStrategyBlock = Field(default_factory=VisualStrategyBlock)
    pacing: MotionProfile = Field(default_factory=MotionProfile)
    transition: TransitionStrategy = Field(default_factory=TransitionStrategy)
    subtitle: SubtitleStrategy = Field(default_factory=SubtitleStrategy)
    audio: AudioStrategy = Field(default_factory=AudioStrategy)

    # Legacy flat fields kept for Rendering Agent compatibility
    visual_strategies: list[VisualStrategy] = Field(default_factory=list)
    cut_frequency: str = "normal"
    transition_type: str = "cut"
    transition_duration: float = 0.0
    music: MusicCue = Field(default_factory=MusicCue)

    narration_text: str = ""
    audio_path: str = ""
    audio_duration: float = 0.0
    editing_window: float = 0.0
    # Human-adjustable nudge: seconds narration start is offset within this
    # segment's window (V2 Director Studio "Adjust Audio"). Rendering-only —
    # never touches Script/Voice.
    audio_offset: float = 0.0

    video_start: float = 0.0
    video_end: float = 0.0
    video_duration: float = 0.0

    timeline_start: float = 0.0
    timeline_end: float = 0.0

    def primary_strategy(self) -> VisualStrategy:
        if self.visual_strategies:
            return self.visual_strategies[0]
        if self.visual_strategy.operations:
            op = self.visual_strategy.operations[0]
            return VisualStrategy(
                type=op.type,
                parameters={**op.parameters, "strength": op.strength, "target": op.target},
                reason=op.reason,
            )
        return VisualStrategy()

    def sync_legacy_fields(self) -> None:
        """Populate flat legacy fields from new structured blocks."""
        self.visual_strategies = [
            VisualStrategy(
                type=op.type,
                parameters={
                    **op.parameters,
                    "strength": op.strength,
                    "target": op.target,
                },
                reason=op.reason,
            )
            for op in self.visual_strategy.operations
        ] or [VisualStrategy(type="clean_cut", reason="default")]

        self.cut_frequency = self.pacing.camera_change_frequency
        self.transition_type = self.transition.type
        self.transition_duration = self.transition.duration
        self.music = MusicCue(
            mood=self.audio.mood,
            energy=0.5,
            volume=self.audio.music_volume,
        )


class EditingPlan(VersionedBaseModel):
    """Complete output of the Editing Strategy Agent."""

    agent_name: str = "editing"
    style: str = ""
    target_audience: str = ""
    llm_used: bool = False
    segments: list[EditingSegmentPlan] = Field(default_factory=list)
