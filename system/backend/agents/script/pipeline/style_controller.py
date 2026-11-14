"""Module 3: Style Controller — rule-only language constraint mapper.

Turns "style" into language constraints. This module NEVER generates
narration content. It only:
1. Derives a StyleConfig (tone, sentence_length, energy) from Director Intent
2. Post-processes already-generated text to fit tone-appropriate vocabulary
   and sentence-length bands (word banning / hard word-count cap)

Duration-based fitting against scene timing belongs to the Alignment
Engine (Module 4), not here.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agents.script.utils import clause_aware_trim, clause_aware_trim_zh
from backend.schemas.script_schema import StyleConfig

logger = logging.getLogger(__name__)

# style -> effect (director vocabulary, deterministic — never generates new content)
SENTENCE_LENGTH_BANDS: dict[str, tuple[int, int]] = {
    "short": (6, 14),
    "medium": (12, 24),
    "long": (18, 34),
}

# Chinese uses character counts instead of space-delimited words.
# Marketing lines need room for evidence + benefit, not just mood.
SENTENCE_LENGTH_BANDS_ZH: dict[str, tuple[int, int]] = {
    "short": (16, 32),
    "medium": (24, 48),
    "long": (36, 68),
}

TONE_BANNED_WORDS: dict[str, list[str]] = {
    "warm": ["clinical", "sterile", "cold", "corporate"],
    "warm_inviting": ["clinical", "sterile", "cold", "corporate"],
    "luxury": ["basic", "plain", "cheap"],
    "premium": ["basic", "plain", "cheap"],
    "minimal": ["ornate", "elaborate", "lavish"],
    "professional": ["awesome", "insane", "crazy"],
}

# Empty aesthetic fragments that signal non-marketing copy (stripped when present).
EMPTY_AESTHETIC_PHRASES_ZH = (
    "以光为魂",
    "以简为美",
    "静诉温润",
    "静候日常",
    "恰如其分",
    "诗意日常",
)

MINIMAL_TONE_KEYWORDS = ("minimal", "modern", "clean")
DYNAMIC_ENERGY_TAGS = ("premium_feel", "modern_style", "cinematic")


class StyleController:
    """Derives and applies style constraints (vocabulary control, not content generation)."""

    def derive_style(
        self,
        intent: dict[str, Any],
        language: str = "en",
    ) -> StyleConfig:
        """Convert DirectorIntent (dict) into concrete language constraints."""
        tone = str(intent.get("emotional_tone", "") or "professional")
        tags = intent.get("intent_tags", []) or []
        tone_lower = tone.lower()
        lang = (language or intent.get("narration_language") or "en").strip().lower()
        if lang not in ("en", "zh"):
            lang = "en"

        sentence_length = "medium"
        if any(kw in tone_lower for kw in MINIMAL_TONE_KEYWORDS):
            sentence_length = "short"
        elif "luxury" in tone_lower or "premium" in tone_lower:
            sentence_length = "long"

        energy = "dynamic" if any(t in tags for t in DYNAMIC_ENERGY_TAGS) else "calm"

        return StyleConfig(
            tone=tone,
            sentence_length=sentence_length,
            energy=energy,
            language=lang,
        )

    def apply(self, text: str, style: StyleConfig) -> str:
        """Apply deterministic vocabulary constraints to already-generated text."""
        cleaned = self._strip_banned_words(text, style.tone)
        if (style.language or "en").lower() == "zh":
            cleaned = self._strip_empty_aesthetic_zh(cleaned)
        cleaned = self._cap_sentence_length(cleaned, style.sentence_length, style.language)
        return cleaned.strip()

    def _strip_empty_aesthetic_zh(self, text: str) -> str:
        cleaned = text
        for phrase in EMPTY_AESTHETIC_PHRASES_ZH:
            if phrase in cleaned:
                cleaned = cleaned.replace(phrase, "")
        # Clean leftover punctuation from removals
        cleaned = cleaned.replace("——", "，").replace("——", "，")
        while "，，" in cleaned:
            cleaned = cleaned.replace("，，", "，")
        return cleaned.strip("，。、； ")

    def _strip_banned_words(self, text: str, tone: str) -> str:
        banned = TONE_BANNED_WORDS.get(tone.lower(), [])
        if not banned:
            for key, words in TONE_BANNED_WORDS.items():
                if key in tone.lower():
                    banned = words
                    break
        if not banned:
            return text

        words = text.split()
        filtered = [w for w in words if w.strip(",.").lower() not in banned]
        if len(filtered) != len(words):
            logger.debug("Style controller stripped banned words for tone=%s", tone)
        return " ".join(filtered)

    def _cap_sentence_length(self, text: str, sentence_length: str, language: str = "en") -> str:
        """Hard cap length per the style's sentence-length band (never adds words)."""
        if (language or "en").lower() == "zh":
            _, max_chars = SENTENCE_LENGTH_BANDS_ZH.get(
                sentence_length, SENTENCE_LENGTH_BANDS_ZH["medium"]
            )
            if len(text) <= max_chars:
                return text
            return clause_aware_trim_zh(text, max_chars)
        _, max_words = SENTENCE_LENGTH_BANDS.get(sentence_length, SENTENCE_LENGTH_BANDS["medium"])
        return clause_aware_trim(text, max_words)
