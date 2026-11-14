"""Capability 4: Pronunciation Control.

Normalizes real-estate text for TTS (numbers, units, addresses).
"""

from __future__ import annotations

import re

from backend.schemas.voice_schema import PronunciationGuide

BEDROOM_RE = re.compile(r"\b(\d+)\s*[-–]?\s*bedroom\b", re.IGNORECASE)
BATHROOM_RE = re.compile(r"\b(\d+)\s*[-–]?\s*bath(room)?\b", re.IGNORECASE)
SQFT_RE = re.compile(r"\b(\d[\d,]*)\s*sq\.?\s*ft\.?\b", re.IGNORECASE)
SLASH_RE = re.compile(r"\s*/\s*")
STREET_ABBR = {
    "st": "Street",
    "ave": "Avenue",
    "rd": "Road",
    "blvd": "Boulevard",
    "ne": "N E",
    "nw": "N W",
    "se": "S E",
    "sw": "S W",
}


class PronunciationController:
    """Build pronunciation overrides and TTS-ready text."""

    def analyze(self, text: str) -> PronunciationGuide:
        replacements: dict[str, str] = {}

        for match in BEDROOM_RE.finditer(text):
            token = match.group(0)
            num = match.group(1)
            word = self._number_word(int(num))
            spoken = f"{word} bedroom"
            replacements[token.lower()] = spoken

        for match in BATHROOM_RE.finditer(text):
            token = match.group(0)
            num = match.group(1)
            word = self._number_word(int(num))
            spoken = f"{word} bath"
            replacements[token.lower()] = spoken

        for match in SQFT_RE.finditer(text):
            token = match.group(0)
            num = match.group(1).replace(",", "")
            replacements[token.lower()] = f"{num} square feet"

        return PronunciationGuide(replacements=replacements)

    def apply(self, text: str, guide: PronunciationGuide | None = None) -> str:
        guide = guide or self.analyze(text)
        result = text

        for original, spoken in guide.replacements.items():
            pattern = re.compile(re.escape(original), re.IGNORECASE)
            result = pattern.sub(spoken, result)

        result = SLASH_RE.sub(" and ", result)
        result = re.sub(r"\s+", " ", result).strip()
        return result

    def _number_word(self, n: int) -> str:
        words = {
            0: "zero",
            1: "one",
            2: "two",
            3: "three",
            4: "four",
            5: "five",
            6: "six",
            7: "seven",
            8: "eight",
            9: "nine",
            10: "ten",
        }
        return words.get(n, str(n))
