"""Capability 4: Subtitle Director.

Determines subtitle style per segment based on role and story phase.
"""

from __future__ import annotations

from backend.schemas.editing_schema import SubtitleStyle

# Fixed display size — renderer also enforces FIXED_FONT_SIZE
FIXED_FONT_SIZE = 30


class SubtitleDirector:
    """Decide subtitle style for a timeline segment."""

    def direct(self, tl_seg: dict, highlight_words: list[str] | None = None) -> SubtitleStyle:
        role = tl_seg.get("role", "SUPPORT")
        story_phase = tl_seg.get("visual_plan", {}).get("story_phase", "")
        narr_text = tl_seg.get("narration", {}).get("text", "")

        enabled = bool(narr_text.strip())

        bg_opacity = 0.55
        animation = "fade"

        if role == "HERO":
            bg_opacity = 0.65
        elif role == "TRANSITION":
            bg_opacity = 0.40

        if story_phase in ("opening_hook", "signature_close"):
            animation = "fade"
        elif story_phase == "emotional_center":
            bg_opacity = 0.60

        return SubtitleStyle(
            enabled=enabled,
            font_size=FIXED_FONT_SIZE,
            color="white",
            bg_opacity=bg_opacity,
            position="bottom",
            animation=animation,
            highlight_words=highlight_words or [],
            max_chars_per_line=40,
        )
