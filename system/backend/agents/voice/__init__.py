"""Voice Agent - Reasoning Layer.

Converts narration script into AI-generated voice audio.
Uses 火山引擎 TTS as the primary provider.
Answers: How long is the actual narration?
"""

from backend.agents.voice.agent import VoiceAgent

__all__ = ["VoiceAgent"]
