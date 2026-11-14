"""Voice Agent schema models — Temporal Voice Director output.

Voice Agent transforms time-aligned narration scripts into expressive
voice specifications. It does NOT synthesize audio; that belongs to the
Voice Execution Service (execution layer).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas.common import VersionedBaseModel


class VoiceProfile(BaseModel):
    """Global voice personality selected for the production."""

    provider: str = "volcengine"
    voice_id: str = ""
    gender: str = "female"
    age: str = "30-40"
    tone: str = "warm"
    style: str = "luxury_real_estate"
    emotion: str = "confident"
    resource_id: str = "seed-tts-1.0"


class VoiceDelivery(BaseModel):
    """Per-segment expressive delivery instructions."""

    emotion: str = "neutral"
    speed: float = 1.0  # multiplier, 1.0 = normal
    pitch: str = "medium"  # low | medium | high
    pause_before: float = 0.0
    pause_after: float = 0.0
    energy: str = "medium"  # low | medium | high


class PronunciationGuide(BaseModel):
    """Custom pronunciation overrides for TTS."""

    replacements: dict[str, str] = Field(default_factory=dict)


class VoiceSegmentPlan(BaseModel):
    """One voice specification bound to a script narration segment."""

    id: str = ""
    script_id: str = ""
    text: str = ""
    tts_text: str = ""  # text after pronunciation normalization

    delivery: VoiceDelivery = Field(default_factory=VoiceDelivery)
    pronunciation: PronunciationGuide = Field(default_factory=PronunciationGuide)

    estimated_duration: float = 0.0
    estimated_words: int = 0
    speech_rate: float = 2.3  # English words per second at chosen speed
    scene_duration: float = 0.0
    duration_delta: float = 0.0  # estimated_duration - scene_duration
    needs_timeline_adjustment: bool = False


class TimelineConstraintSummary(BaseModel):
    """Aggregated voice-vs-video timing signals for Timeline Optimization."""

    total_scene_duration: float = 0.0
    total_estimated_voice_duration: float = 0.0
    total_duration_delta: float = 0.0
    segments_over_budget: list[str] = Field(default_factory=list)
    segments_under_budget: list[str] = Field(default_factory=list)


class VoicePlan(BaseModel):
    """Complete voice direction plan produced by Voice Agent."""

    profile: VoiceProfile = Field(default_factory=VoiceProfile)
    segments: list[VoiceSegmentPlan] = Field(default_factory=list)
    timeline_summary: TimelineConstraintSummary = Field(
        default_factory=TimelineConstraintSummary
    )


class VoiceAgentOutput(VersionedBaseModel):
    """Reasoning-layer output of the Voice Agent (Temporal Voice Director)."""

    agent_name: str = "voice"
    voice_plan: VoicePlan = Field(default_factory=VoicePlan)


class ExecutedAudioSegment(BaseModel):
    """Actual synthesized audio for one voice segment."""

    segment_id: str = ""
    script_id: str = ""
    audio_path: str = ""
    duration: float = 0.0
    estimated_duration: float = 0.0
    duration_delta: float = 0.0


class VoiceExecutionResult(VersionedBaseModel):
    """Output of the Voice Execution Service (TTS engine layer)."""

    agent_name: str = "voice_execution"
    provider: str = "volcengine"
    audio_format: str = "mp3"
    sample_rate: int = 24000
    total_duration: float = 0.0
    segments: list[ExecutedAudioSegment] = Field(default_factory=list)
    full_audio_path: str = ""


# Backward-compat aliases (older stub schema)
AudioSegment = ExecutedAudioSegment
VoiceOutput = VoiceExecutionResult
