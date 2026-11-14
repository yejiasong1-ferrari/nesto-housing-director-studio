"""Abstract TTS provider interface.

All TTS providers must implement this interface. The system uses
火山引擎 TTS as the primary provider but can support others.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class TTSRequest(BaseModel):
    """Request to generate speech from text."""

    text: str
    voice_id: str = ""
    speed: float = 1.0
    volume: float = 1.0
    pitch: float = 1.0
    output_format: str = "mp3"
    sample_rate: int = 24000


class TTSResponse(BaseModel):
    """Response from a TTS provider."""

    audio_path: Path
    duration: float
    sample_rate: int = 24000
    format: str = "mp3"
    size_bytes: int = 0


class TTSProvider(ABC):
    """Abstract base class for TTS providers.

    Every TTS provider must implement synthesize() and
    synthesize_segments(). This abstraction allows the system
    to swap between 火山引擎, ElevenLabs, OpenAI TTS, etc.
    """

    provider_name: str = "base"

    @abstractmethod
    async def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResponse:
        """Synthesize speech from a single text input.

        Args:
            request: TTS request with text and voice settings.
            output_path: Where to save the audio file.

        Returns:
            TTSResponse with audio metadata.
        """
        ...

    @abstractmethod
    async def synthesize_segments(
        self,
        segments: list[TTSRequest],
        output_dir: Path,
    ) -> list[TTSResponse]:
        """Synthesize speech from multiple text segments.

        Args:
            segments: List of TTS requests, one per segment.
            output_dir: Directory to save audio files.

        Returns:
            List of TTSResponse with audio metadata for each segment.
        """
        ...

    @abstractmethod
    async def get_available_voices(self) -> list[dict[str, Any]]:
        """List available voices from the TTS provider.

        Returns:
            List of voice descriptors with id, name, language, etc.
        """
        ...
