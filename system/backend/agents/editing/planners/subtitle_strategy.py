"""Subtitle Strategy — how narration text is displayed (not what it says)."""

from __future__ import annotations

from backend.schemas.editing_schema import DirectorDecision, SubtitleStrategy

# font_size is fixed at render time; presets only vary opacity / animation
FIXED_FONT_SIZE = 30

STYLE_PRESETS: dict[str, dict] = {
    "premium": {"font_size": FIXED_FONT_SIZE, "bg_opacity": 0.65, "animation": "fade"},
    "minimal": {"font_size": FIXED_FONT_SIZE, "bg_opacity": 0.50, "animation": "fade"},
    "none": {"font_size": FIXED_FONT_SIZE, "bg_opacity": 0.40, "animation": "none"},
}

LIGHT_KEYWORDS = {"natural light", "sunlight", "window", "skylight", "bright"}
SPACE_KEYWORDS = {
    "island", "marble", "countertop", "hardwood", "open concept",
    "open-concept", "kitchen", "living",
}


class SubtitleStrategyPlanner:
    def plan(
        self,
        tl_seg: dict,
        decision: DirectorDecision,
        narration_text: str,
    ) -> SubtitleStrategy:
        if not narration_text.strip():
            return SubtitleStrategy(enabled=False, style="none")

        hint = (decision.subtitle_hint or "").lower()
        role = tl_seg.get("role", "SUPPORT")

        if hint == "none":
            style_name = "minimal"
        elif hint in STYLE_PRESETS:
            style_name = hint
        elif role == "HERO":
            style_name = "premium"
        elif role == "TRANSITION":
            style_name = "minimal"
        else:
            style_name = "minimal"

        preset = STYLE_PRESETS[style_name]
        highlights = self._highlights(narration_text, decision)

        return SubtitleStrategy(
            enabled=style_name != "none",
            style=style_name,
            position="bottom_safe",
            animation=preset["animation"],
            highlight=highlights,
            font_size=FIXED_FONT_SIZE,
            color="white",
            bg_opacity=preset["bg_opacity"],
            max_chars_per_line=40,
        )

    def _highlights(self, text: str, decision: DirectorDecision) -> list[str]:
        text_lower = text.lower()
        out: list[str] = []
        for f in decision.focus_order:
            el = f.element.lower()
            if el and el in text_lower and el not in out:
                out.append(f.element)
            if len(out) >= 3:
                return out
        for kw in sorted(LIGHT_KEYWORDS | SPACE_KEYWORDS):
            if kw in text_lower and kw not in out:
                out.append(kw)
            if len(out) >= 3:
                break
        return out
