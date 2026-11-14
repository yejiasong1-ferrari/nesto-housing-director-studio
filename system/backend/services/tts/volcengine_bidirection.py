"""Volcengine V3 bidirectional TTS WebSocket client."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from backend.services.tts.volcengine_protocol import (
    EventReceive,
    EventSend,
    MessageType,
    build_frame,
    parse_frame,
)

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
DEFAULT_RESOURCE_ID = "seed-tts-1.0"
# Default Chinese tour voice (爽快思思). English callers may override via voice plan.
DEFAULT_SPEAKER = "zh_male_wennuanahu_moon_bigtts"


def speed_to_speech_rate(speed: float) -> int:
    """Convert 0.5–2.0 speed multiplier to Volcengine speech_rate (-50..100)."""
    rate = int(round((speed - 1.0) * 100))
    return max(-50, min(100, rate))


class VolcengineBidirectionalTTS:
    """Synthesize speech via Volcengine V3 bidirectional WebSocket API."""

    def __init__(
        self,
        api_key: str,
        endpoint: str = DEFAULT_ENDPOINT,
        resource_id: str = DEFAULT_RESOURCE_ID,
        default_speaker: str = DEFAULT_SPEAKER,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.resource_id = resource_id
        self.default_speaker = default_speaker

    async def synthesize_text(
        self,
        text: str,
        output_path: Path,
        *,
        speaker: str | None = None,
        speed: float = 1.0,
        sample_rate: int = 24000,
        audio_format: str = "mp3",
    ) -> float:
        """Synthesize one text utterance and return measured duration in seconds."""
        try:
            import websockets
        except ImportError as exc:
            raise ImportError(
                "websockets package is required for Volcengine bidirectional TTS. "
                "Install with: pip install websockets"
            ) from exc

        speaker = speaker or self.default_speaker
        session_id = str(uuid.uuid4())
        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        speech_rate = speed_to_speech_rate(speed)
        audio_params = {
            "format": audio_format,
            "sample_rate": sample_rate,
            "speech_rate": speech_rate,
        }

        audio_chunks: list[bytes] = []

        async with websockets.connect(
            self.endpoint,
            additional_headers=headers,
            max_size=16 * 1024 * 1024,
        ) as ws:
            await ws.send(build_frame(EventSend.StartConnection))
            await self._recv_until(ws, {EventReceive.ConnectionStarted})

            session_payload = {
                "user": {"uid": "ai-director"},
                "namespace": "BidirectionalTTS",
                "event": int(EventSend.StartSession),
                "req_params": {
                    "speaker": speaker,
                    "audio_params": audio_params,
                },
            }
            await ws.send(
                build_frame(EventSend.StartSession, session_payload, session_id=session_id)
            )
            await self._recv_until(ws, {EventReceive.SessionStarted})

            task_payload = {
                "namespace": "BidirectionalTTS",
                "event": int(EventSend.TaskRequest),
                "req_params": {
                    "text": text,
                    "speaker": speaker,
                    "audio_params": audio_params,
                },
            }
            await ws.send(
                build_frame(EventSend.TaskRequest, task_payload, session_id=session_id)
            )
            # Signal end of input immediately so server starts flushing all audio.
            # Audio collection then runs until SessionFinished (covers all sentences).
            await ws.send(build_frame(EventSend.FinishSession, {}, session_id=session_id))

            await self._collect_audio(ws, audio_chunks)

            await ws.send(build_frame(EventSend.FinishConnection))
            await self._recv_until(ws, {EventReceive.ConnectionFinished}, timeout=10)

        if not audio_chunks:
            raise RuntimeError("No audio received from Volcengine TTS")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"".join(audio_chunks))
        measured = self._measure_duration(output_path)
        logger.info(
            "Synthesized %d bytes -> %s (%.2fs)",
            sum(len(c) for c in audio_chunks),
            output_path,
            measured,
        )
        return measured

    async def _recv_until(
        self,
        ws: object,
        expected: set[EventReceive],
        timeout: float = 30,
    ) -> tuple[int, str, bytes]:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = max(0.1, deadline - asyncio.get_event_loop().time())
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)  # type: ignore[attr-defined]
            event, session_id, payload = self._parse_server_frame(raw)
            if event in expected:
                return event, session_id, payload
        raise TimeoutError(f"Timed out waiting for events {expected}")

    async def _collect_audio(self, ws: object, chunks: list[bytes]) -> None:
        """Collect all audio frames until the server signals SessionFinished.

        FinishSession is sent before this method is called, so the server
        knows all text has been submitted and will flush every sentence before
        sending SessionFinished.
        """
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)  # type: ignore[attr-defined]
            msg_type, event, payload, sequence = self._frame_meta(raw)

            if msg_type == int(MessageType.ERROR):
                detail = payload.decode("utf-8", errors="replace")
                raise RuntimeError(f"Volcengine TTS error: {detail}")

            if event == int(EventReceive.SessionFailed):
                raise RuntimeError(payload.decode("utf-8", errors="replace"))

            # Audio frames (AUDIO_ONLY_SERVER carrying TTSResponse event)
            if msg_type == int(MessageType.AUDIO_ONLY_SERVER) and payload:
                chunks.append(payload)
                continue

            # Metadata events — sentence boundaries, keep reading
            if event in (
                int(EventReceive.TTSSentenceStart),
                int(EventReceive.TTSSentenceEnd),
                int(EventReceive.TTSEnded),
                int(EventReceive.UsageResponse),
            ):
                continue

            # Server has flushed all audio for this session
            if event == int(EventReceive.SessionFinished):
                return

    def _frame_meta(self, raw: bytes | str) -> tuple[int, int, bytes, int]:
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        msg_type = (raw[1] >> 4) & 0x0F if len(raw) > 1 else 0
        event, _, payload, sequence = parse_frame(raw)
        return msg_type, event, payload, sequence

    def _parse_server_frame(self, raw: bytes | str) -> tuple[int, str, bytes]:
        msg_type, event, payload, _ = self._frame_meta(raw)
        if msg_type == int(MessageType.ERROR):
            raise RuntimeError(f"Volcengine TTS error: {payload.decode('utf-8', errors='replace')}")
        if event in (int(EventReceive.ConnectionFailed), int(EventReceive.SessionFailed)):
            raise RuntimeError(payload.decode("utf-8", errors="replace"))
        _, session_id, payload, _ = parse_frame(raw if isinstance(raw, bytes) else raw.encode())
        return event, session_id, payload

    def _measure_duration(self, path: Path) -> float:
        """Return on-disk playback duration.

        Must use ffprobe (or mutagen), not ``bytes / 16000``. That fallback
        assumes 128 kbps CBR; Volcengine MP3s are often ~64 kbps, so the
        estimate is ~½× real length. Timeline then under-sizes editing
        windows while the renderer places the real file — voice and picture
        drift apart.
        """
        try:
            from backend.tools.audio_utils import get_audio_duration

            probed = get_audio_duration(path)
            if probed > 0.05:
                return probed
        except Exception as exc:
            logger.debug("ffprobe duration failed for %s: %s", path, exc)

        try:
            from mutagen.mp3 import MP3

            length = float(MP3(str(path)).info.length)
            if length > 0.05:
                return length
        except Exception:
            pass

        try:
            from moviepy import AudioFileClip

            clip = AudioFileClip(str(path))
            dur = float(clip.duration or 0)
            clip.close()
            if dur > 0.05:
                return dur
        except Exception:
            logger.debug("moviepy duration failed for %s", path)

        size = path.stat().st_size
        logger.warning(
            "Falling back to byte-size duration for %s (%d bytes) — sync may drift",
            path,
            size,
        )
        return max(size / 16000.0, 0.5)
