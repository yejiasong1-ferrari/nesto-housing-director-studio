"""Capability 2: Visual Emphasis Controller.

Identifies the most important visual element and adds
a highlight directive (zoom target, object focus).
"""

from __future__ import annotations

LIGHT_KEYWORDS = {"natural light", "sunlight", "window", "skylight", "bright"}
SPACE_KEYWORDS = {"island", "countertop", "hardwood", "floor", "ceiling", "open"}


class VisualEmphasis:
    """Derive the primary visual focus element for a segment."""

    def get_focus(self, tl_seg: dict) -> str:
        focus = tl_seg.get("visual_plan", {}).get("focus_elements", [])
        if focus:
            return focus[0]
        narr_text = tl_seg.get("narration", {}).get("text", "").lower()
        for kw in sorted(LIGHT_KEYWORDS | SPACE_KEYWORDS):
            if kw in narr_text:
                return kw
        return tl_seg.get("room_type", "space")

    def get_highlight_words(self, narr_text: str) -> list[str]:
        """Pick 1-3 key phrases from narration text to highlight in subtitles."""
        text_lower = narr_text.lower()
        highlights: list[str] = []
        for kw in LIGHT_KEYWORDS | SPACE_KEYWORDS:
            if kw in text_lower:
                highlights.append(kw)
            if len(highlights) >= 3:
                break
        return highlights
