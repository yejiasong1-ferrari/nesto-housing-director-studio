"""Voice Execution Service — deterministic TTS synthesis layer.

Reads VoicePlan from Voice Agent and produces actual audio files.
This is execution, not cognition.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.schemas.voice_schema import (
    ExecutedAudioSegment,
    VoiceExecutionResult,
    VoicePlan,
)
from backend.services.tts.volcengine_bidirection import (
    DEFAULT_ENDPOINT,
    DEFAULT_SPEAKER,
    VolcengineBidirectionalTTS,
)

logger = logging.getLogger(__name__)


class VoiceExecutionService:
    """Synthesize audio from a VoicePlan using configured TTS provider."""

    def __init__(
        self,
        api_key: str = "",
        endpoint: str = "",
        resource_id: str = "seed-tts-2.0",
        default_speaker: str = "",
        sample_rate: int = 24000,
        audio_format: str = "mp3",
    ) -> None:
        self.sample_rate = sample_rate
        self.audio_format = audio_format
        self.tts = VolcengineBidirectionalTTS(
            api_key=api_key,
            endpoint=endpoint or DEFAULT_ENDPOINT,
            resource_id=resource_id,
            default_speaker=default_speaker or DEFAULT_SPEAKER,
        )

    async def synthesize_plan(
        self,
        voice_plan: VoicePlan | dict[str, Any],
        output_dir: Path,
        project_id: str = "",
    ) -> VoiceExecutionResult:
        """Synthesize all segments in a voice plan."""
        if isinstance(voice_plan, dict):
            plan = VoicePlan.model_validate(voice_plan)
        else:
            plan = voice_plan

        output_dir.mkdir(parents=True, exist_ok=True)
        executed: list[ExecutedAudioSegment] = []
        total_duration = 0.0

        speaker = plan.profile.voice_id

        for seg in plan.segments:
            text = seg.tts_text or seg.text
            if not text.strip():
                continue

            out_path = output_dir / f"{seg.script_id}.{self.audio_format}"
            logger.info("Synthesizing %s (%d chars)...", seg.script_id, len(text))

            duration = await self.tts.synthesize_text(
                text=text,
                output_path=out_path,
                speaker=speaker,
                speed=seg.delivery.speed,
                sample_rate=self.sample_rate,
                audio_format=self.audio_format,
            )

            delta = round(duration - seg.estimated_duration, 2)
            executed.append(
                ExecutedAudioSegment(
                    segment_id=seg.id,
                    script_id=seg.script_id,
                    audio_path=str(out_path),
                    duration=round(duration, 2),
                    estimated_duration=seg.estimated_duration,
                    duration_delta=delta,
                )
            )
            total_duration += duration

        return VoiceExecutionResult(
            project_id=project_id,
            provider=plan.profile.provider,
            audio_format=self.audio_format,
            sample_rate=self.sample_rate,
            total_duration=round(total_duration, 2),
            segments=executed,
        )
