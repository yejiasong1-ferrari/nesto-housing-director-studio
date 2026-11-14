"""Capability 1: Voice Style Selection.

Maps Director Intent + script tone into a global voice profile.
Rule-based — no TTS, no audio generation.
"""

from __future__ import annotations

from typing import Any

from backend.schemas.voice_schema import VoiceProfile

# Default Chinese tour voice: 温暖阿虎 (seed-tts-1.0 / moon_bigtts)
ZH_DEFAULT_VOICE = "zh_male_wennuanahu_moon_bigtts"
# English keeps the verified bilingual conversation speaker
EN_DEFAULT_VOICE = "zh_male_M392_conversation_wvae_bigtts"

STYLE_VOICE_MAP: dict[str, dict[str, str]] = {
    "luxury": {
        "gender": "male",
        "age": "30-40",
        "tone": "calm",
        "style": "luxury_real_estate",
        "emotion": "confident",
        "voice_id": ZH_DEFAULT_VOICE,
    },
    "warm_luxury": {
        "gender": "male",
        "age": "30-40",
        "tone": "warm",
        "style": "warm_luxury_real_estate",
        "emotion": "confident",
        "voice_id": ZH_DEFAULT_VOICE,
    },
    "warm_modern_luxury": {
        "gender": "male",
        "age": "28-38",
        "tone": "warm",
        "style": "warm_modern_luxury",
        "emotion": "confident",
        "voice_id": ZH_DEFAULT_VOICE,
    },
    "family": {
        "gender": "male",
        "age": "28-35",
        "tone": "warm",
        "style": "family_friendly",
        "emotion": "friendly",
        "voice_id": ZH_DEFAULT_VOICE,
    },
    "rental": {
        "gender": "male",
        "age": "25-35",
        "tone": "clear",
        "style": "informative_rental",
        "emotion": "neutral",
        "voice_id": ZH_DEFAULT_VOICE,
    },
    "professional": {
        "gender": "male",
        "age": "30-45",
        "tone": "clear",
        "style": "professional_real_estate",
        "emotion": "confident",
        "voice_id": ZH_DEFAULT_VOICE,
    },
}

# seed-tts-1.0 speakers: Chinese → 温暖阿虎; English → verified M392.
VOICE_ID_BY_LANGUAGE: dict[str, str] = {
    "en": EN_DEFAULT_VOICE,
    "zh": ZH_DEFAULT_VOICE,
}

AUDIENCE_STYLE_HINTS: dict[str, str] = {
    "young_family": "family",
    "young_couple": "warm_luxury",
    "investor": "professional",
    "renter": "rental",
}


class StyleSelector:
    """Select global voice personality from director intent."""

    def select(
        self,
        intent: dict[str, Any],
        script_style: dict[str, Any] | None = None,
        provider: str = "volcengine",
        default_voice_id: str = "",
        language: str = "en",
    ) -> VoiceProfile:
        tone = str(intent.get("emotional_tone", "") or "professional").lower()
        audience = str(intent.get("target_audience", "") or "").lower()
        script_style = script_style or {}
        lang = (
            language
            or script_style.get("language")
            or intent.get("narration_language")
            or "en"
        )
        lang = str(lang).strip().lower()
        if lang not in ("en", "zh"):
            lang = "en"

        style_key = self._resolve_style_key(tone, audience, script_style)
        preset = STYLE_VOICE_MAP.get(style_key, STYLE_VOICE_MAP["professional"])

        voice_id = (
            default_voice_id
            or VOICE_ID_BY_LANGUAGE.get(lang)
            or preset["voice_id"]
        )
        return VoiceProfile(
            provider=provider,
            voice_id=voice_id,
            gender=preset["gender"],
            age=preset["age"],
            tone=preset["tone"],
            style=preset["style"],
            emotion=preset["emotion"],
        )

    def _resolve_style_key(
        self,
        tone: str,
        audience: str,
        script_style: dict[str, Any],
    ) -> str:
        if audience in AUDIENCE_STYLE_HINTS:
            return AUDIENCE_STYLE_HINTS[audience]

        script_tone = str(script_style.get("tone", "")).lower()
        for key in STYLE_VOICE_MAP:
            if key in tone or key in script_tone:
                return key

        if "luxury" in tone or "premium" in tone:
            return "luxury"
        if "warm" in tone:
            return "warm_luxury"
        if "rental" in tone:
            return "rental"
        return "professional"
