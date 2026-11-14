"""Vision Knowledge Base (VKB) schema models.

The Vision Agent outputs a Vision Knowledge Base consisting of two layers:
- Raw Layer: objective, verifiable facts (timestamps, keyframe paths)
- Knowledge Layer: LLM-reasoned understanding (room type, style, selling points)

Plus a Candidate Attention Map that suggests visual importance
without making the final editorial decision (that belongs to Planner).

Principle: Perceive Once, Reuse Everywhere.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


# ── Raw Layer ──────────────────────────────────────────────


class VideoIndex(BaseModel):
    """Technical video metadata established during preprocessing."""

    file_path: str = ""
    duration: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = ""
    frame_count: int = 0


class RawSegment(BaseModel):
    """Raw objective data for a temporal segment.

    Contains only verifiable facts: timestamps and keyframe file paths.
    No interpretation or naming.
    """

    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    keyframes: list[str] = Field(default_factory=list)


# ── Knowledge Layer ─────────────────────────────────────────


class CameraKnowledge(BaseModel):
    """LLM-reasoned camera motion description."""

    motion: str = ""  # Forward, Pan Left, Pan Right, Static, etc.
    speed: str = ""  # Slow, Medium, Fast
    stability: str = ""  # Stable, Slightly Shaky, Shaky


class SpaceEvidence(BaseModel):
    """Why a space label is trusted (or rejected).

    Hard fixtures beat soft style cues; negative features contradict the label.
    """

    hard_features: list[str] = Field(default_factory=list)
    soft_features: list[str] = Field(default_factory=list)
    negative_features: list[str] = Field(default_factory=list)
    evidence_score: float = 0.0  # 0..1 grounded confidence
    verified: bool = True  # False only after explicit gate rejection
    reject_reason: str = ""


class SpaceInventoryItem(BaseModel):
    """A unique property space discovered inside a temporal segment.

    Long / mixed segments may contain multiple spaces (e.g. Bedroom,
    Study). Short segments typically have a single item.

    Identity vs presentation:
    - ``type`` + ``instance`` / ``instance_id`` — stable internal IDs
      for tracking (e.g. ``Bedroom_4``). Never spoken in narration.
    - ``display_name`` — UI / Detected-spaces label (no instance numbers).
    - ``narration_name`` — Script Agent speakable label only.
    - ``room_role`` — editorial role (primary / secondary / shared / …).
    - ``evidence`` — Verified Space Layer grounding (hard/soft/negative).
    """

    type: str = ""
    instance: int = 1
    instance_id: str = ""
    confidence: float = 0.0
    features: list[str] = Field(default_factory=list)
    display_name: str = ""
    narration_name: str = ""
    room_role: str = ""
    evidence: SpaceEvidence = Field(default_factory=SpaceEvidence)


class RoomKnowledge(BaseModel):
    """LLM-reasoned room understanding.

    This is the primary knowledge that downstream agents consume.
    Planner reads this, never the raw video.

    ``room_type`` is the primary / segment-level label (may be Mixed).
    ``spaces`` is the full property-space inventory for this segment.
    """

    room_type: str = ""
    confidence: float = 0.0
    style: str = ""
    layout: str = ""
    lighting: str = ""
    selling_points: list[str] = Field(default_factory=list)
    furniture: list[str] = Field(default_factory=list)
    appliances: list[str] = Field(default_factory=list)
    camera: CameraKnowledge = Field(default_factory=CameraKnowledge)
    notes: str = ""
    spaces: list[SpaceInventoryItem] = Field(default_factory=list)


# ── Candidate Attention Map ────────────────────────────────


class AttentionCandidate(BaseModel):
    """A visual element that naturally attracts attention.

    Vision Agent identifies what is visually prominent.
    Planner decides what should be emphasized editorially.
    Editing Strategy decides how to highlight it.

    These three responsibilities are fully decoupled.
    """

    target: str = ""  # e.g. "Kitchen Island", "Floor-to-ceiling Window"
    segment_id: str = ""  # which segment this belongs to
    score: float = 0.0  # 0.0 to 1.0 - visual prominence
    reason: str = ""  # why this element is visually notable


# ── VKB Segment (combines Raw + Knowledge) ─────────────────


class VKBSegment(BaseModel):
    """A single spatial segment in the Vision Knowledge Base.

    Combines the raw factual layer and the knowledge reasoning layer
    for one room/area in the walkthrough video.
    """

    segment_id: str = ""
    confidence: float = 0.0
    raw: RawSegment = Field(default_factory=RawSegment)
    knowledge: RoomKnowledge = Field(default_factory=RoomKnowledge)
    # Absolute video time (seconds) when this segment's primary room is
    # first confirmable. Default 0 means unset; consumers treat that as
    # ``raw.start_time``. Conservative: prefer late over early.
    room_visible_start: float = 0.0
    room_visible_end: float = 0.0
    room_stage: str = "interior"


# ── Vision Knowledge Base (top-level output) ──────────────


class VisionKnowledgeBase(VersionedBaseModel):
    """Complete output of the Vision Agent (Spatial Perception Engine).

    This is the single source of truth for the entire AI Director system.
    All downstream agents (Planner, Script, Editing Strategy, Evaluation)
    read from this VKB and never re-analyze the video.

    Principle: Perceive Once, Reuse Everywhere.
    """

    agent_name: str = "vision"
    video: VideoIndex = Field(default_factory=VideoIndex)
    segments: list[VKBSegment] = Field(default_factory=list)
    candidate_attention: list[AttentionCandidate] = Field(default_factory=list)
