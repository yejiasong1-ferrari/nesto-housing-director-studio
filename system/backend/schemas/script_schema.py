"""Script Agent schema models — Temporal Narration Graph.

Script Agent is a temporal narration compiler: it converts structured
scene semantics (Vision) + editorial decisions (Planner) into
time-aligned, TTS-ready narration segments. It never invents timeline
structure — it only compiles language bound to the fixed timeline.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


class StyleConfig(BaseModel):
    """Style constraints derived from director intent (Module 3 input/output)."""

    tone: str = "professional"
    sentence_length: str = "medium"  # short | medium | long
    energy: str = "calm"  # calm | dynamic
    # Narration language for LLM + TTS: en | zh
    language: str = "en"


class NarrativeStructure(BaseModel):
    """Module 1 output: director narrative structure over the fixed timeline."""

    story_arc: list[str] = Field(default_factory=list)  # per-scene arc label, video order
    scene_order: list[str] = Field(default_factory=list)  # segment_ids, video order (unchanged)


class NarrationSegment(BaseModel):
    """One compiled narration unit, bound 1:1 to a Vision/Planner scene.

    This is a node in the Temporal Narration Graph. It must always carry
    a segment_id, a fixed start/end time, and be directly consumable by
    the Voice Agent (TTS).
    """

    segment_id: str = ""
    scene_id: str = ""  # == segment_id (1 scene -> 1 narration)

    start_time: float = 0.0
    end_time: float = 0.0

    text: str = ""
    arc_stage: str = ""  # hook | explore | highlight | close
    role: str = ""  # HERO | SUPPORT | TRANSITION (from Planner hierarchy)

    emotion: str = "neutral"
    voice_style: str = "calm_professional"

    information_density: float = 0.5  # 0..1, how much factual content per second
    importance: float = 0.5  # carried over from Planner attention score

    word_count: int = 0
    estimated_duration: float = 0.0  # seconds, at configured speaking rate
    scene_duration: float = 0.0

    alignment_status: str = "ok"  # ok | compressed | extended | needs_rewrite
    alignment_notes: list[str] = Field(default_factory=list)

    # backward-compat fields (previous stub schema)
    room_type: str = ""
    estimated_duration_legacy: float = 0.0
    tone: str = "professional"
    emphasis_words: list[str] = Field(default_factory=list)
    subtitle_text: str = ""


class ScriptValidation(BaseModel):
    """Quality/consistency validation report for the compiled script."""

    is_valid: bool = True
    issues: list[str] = Field(default_factory=list)
    needs_rewrite_segments: list[str] = Field(default_factory=list)


class ScriptOutput(VersionedBaseModel):
    """Complete output of the Script Agent — the Temporal Narration Graph.

    Answers: How should the property be described, in time-aligned,
    voiceable narration? Does NOT own timeline structure; complies with
    Planner-decided segment boundaries and Timeline Optimization Agent
    constraints downstream.
    """

    agent_name: str = "script"
    script_version: str = "1.0"

    style: StyleConfig = Field(default_factory=StyleConfig)
    narrative_structure: NarrativeStructure = Field(default_factory=NarrativeStructure)
    narration_segments: list[NarrationSegment] = Field(default_factory=list)
    validation: ScriptValidation = Field(default_factory=ScriptValidation)

    total_estimated_duration: float = 0.0
    intro_text: str = ""
    outro_text: str = ""

    # backward-compat alias for older consumers
    @property
    def segments(self) -> list[NarrationSegment]:
        return self.narration_segments


NarrationScript = ScriptOutput
