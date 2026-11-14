"""Subtitle Processor — burn narration text as subtitle overlay.

Uses PIL for text rendering (no ImageMagick dependency).
Fixed font size + generous horizontal margins so text stays on-screen.

CJK (Chinese) narration requires a font with Han glyphs. Latin-only faces
like Arial render Chinese as blank — so font selection is language-aware.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Prefer CJK-capable faces first when Chinese is present.
CJK_FONT_PATHS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    # Common Linux / Docker installs
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]

LATIN_FONT_PATHS = [
    "/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

# Fixed display constants (do not vary per segment role)
FIXED_FONT_SIZE = 30
# Horizontal inset as fraction of frame width (each side)
SIDE_MARGIN_RATIO = 0.10
# Absolute minimum inset in pixels
MIN_SIDE_MARGIN_PX = 120
# Bottom safe area above frame edge. Many source listing videos already carry
# room labels / URLs in the bottom band, so keep generated subtitles slightly
# higher than the raw footage captions.
BOTTOM_MARGIN_PX = 84
# Allow a third wrapped line — 140px only fit two (line_h=40 + pad).
MAX_SUBTITLE_LINES = 3


def _contains_cjk(text: str) -> bool:
    """True if text includes CJK Unified Ideographs (or common extension A)."""
    for ch in text:
        code = ord(ch)
        if (
            0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
            or 0x3400 <= code <= 0x4DBF  # Extension A
            or 0xF900 <= code <= 0xFAFF  # Compatibility Ideographs
            or 0x3000 <= code <= 0x303F  # CJK punctuation
        ):
            return True
    return False


def _try_truetype(path: str, size: int):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(path, size)
    except Exception:
        # .ttc collections may need an explicit face index
        for index in range(0, 6):
            try:
                return ImageFont.truetype(path, size, index=index)
            except Exception:
                continue
    return None


def _load_font(size: int, text: str = ""):
    from PIL import ImageFont

    prefer_cjk = _contains_cjk(text)
    paths = (CJK_FONT_PATHS + LATIN_FONT_PATHS) if prefer_cjk else (LATIN_FONT_PATHS + CJK_FONT_PATHS)

    for path in paths:
        if not Path(path).exists():
            continue
        font = _try_truetype(path, size)
        if font is not None:
            if prefer_cjk:
                logger.debug("Subtitle font (CJK): %s", path)
            return font

    logger.warning(
        "No TrueType subtitle font found — Chinese glyphs may be missing"
    )
    return ImageFont.load_default()


def _text_width(draw, text: str, font) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except Exception:
        return len(text) * (FIXED_FONT_SIZE // 2)


def _wrap_by_char_width(draw, text: str, font, max_width: int) -> list[str]:
    """Character-wrap for CJK / unspaced text."""
    lines: list[str] = []
    buf = ""
    for ch in text:
        if ch == "\n":
            if buf:
                lines.append(buf)
            buf = ""
            continue
        trial = buf + ch
        if buf and _text_width(draw, trial, font) > max_width:
            lines.append(buf)
            buf = ch
        else:
            buf = trial
    if buf:
        lines.append(buf)
    return lines or [""]


def _wrap_by_pixel_width(draw, text: str, font, max_width: int) -> list[str]:
    """Word-wrap so each line fits within max_width pixels."""
    # Chinese / unspaced lines: wrap by character, not whitespace tokens
    stripped = text.strip()
    if _contains_cjk(stripped) or " " not in stripped:
        return _wrap_by_char_width(draw, stripped, font, max_width)

    words = stripped.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)

    # Hard-split any single word that still overflows
    final: list[str] = []
    for line in lines:
        if _text_width(draw, line, font) <= max_width:
            final.append(line)
            continue
        final.extend(_wrap_by_char_width(draw, line, font, max_width))
    return final or [""]


def _make_subtitle_image(
    text: str,
    clip_width: int,
    clip_height: int,
    font_size: int = FIXED_FONT_SIZE,
    bg_opacity: float = 0.55,
    position: str = "bottom_safe",
) -> np.ndarray:
    from PIL import Image, ImageDraw

    side_margin = max(MIN_SIDE_MARGIN_PX, int(clip_width * SIDE_MARGIN_RATIO))
    max_text_width = max(80, clip_width - 2 * side_margin)

    font = _load_font(font_size, text)
    # Temporary draw context for measuring
    measure = Image.new("RGBA", (clip_width, 64), (0, 0, 0, 0))
    measure_draw = ImageDraw.Draw(measure)
    lines = _wrap_by_pixel_width(measure_draw, text.strip(), font, max_text_width)

    line_h = font_size + 10
    pad_y = 14
    lines = lines[:MAX_SUBTITLE_LINES]
    bar_h = len(lines) * line_h + pad_y * 2

    bar = Image.new("RGBA", (clip_width, bar_h), (0, 0, 0, int(255 * bg_opacity)))
    draw = ImageDraw.Draw(bar)

    y = pad_y
    for line in lines:
        tw = _text_width(draw, line, font)
        # Center within the safe horizontal band
        x = side_margin + max(0, (max_text_width - tw) // 2)
        # Clamp so glyphs never leave the margin band
        x = min(max(side_margin, x), clip_width - side_margin - tw)
        x = max(side_margin, x)
        draw.text((x + 1, y + 1), line, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    canvas = Image.new("RGBA", (clip_width, clip_height), (0, 0, 0, 0))
    pos = (position or "bottom_safe").lower()
    if pos in {"upper_bottom", "above_source_caption", "bottom_safe"}:
        y_pos = clip_height - bar_h - BOTTOM_MARGIN_PX
    elif pos in {"middle_lower", "lower_third"}:
        y_pos = int(clip_height * 0.62)
    else:
        y_pos = clip_height - bar_h - 36
    y_pos = max(0, min(y_pos, clip_height - bar_h))
    canvas.paste(bar, (0, y_pos))
    return np.array(canvas)


class SubtitleProcessor:
    """Overlay subtitle text onto a video clip using PIL."""

    def add(self, clip, text: str, style) -> object:
        enabled = bool(getattr(style, "enabled", True))
        if not enabled or not text.strip():
            return clip

        try:
            return self._composite_subtitle(clip, text, style)
        except Exception as exc:
            logger.warning("Subtitle rendering failed (%s) — skipping subtitles", exc)
            return clip

    def _composite_subtitle(self, clip, text: str, style) -> object:
        from moviepy import CompositeVideoClip, ImageClip

        w, h = clip.size
        # Fixed size — ignore per-segment font_size from editing plan
        bg_opacity = float(getattr(style, "bg_opacity", 0.55) or 0.55)
        subtitle_arr = _make_subtitle_image(
            text, w, h,
            font_size=FIXED_FONT_SIZE,
            bg_opacity=bg_opacity,
            position=getattr(style, "position", "bottom_safe"),
        )

        rgb = subtitle_arr[:, :, :3]
        alpha = subtitle_arr[:, :, 3] / 255.0

        sub_clip = ImageClip(rgb, duration=clip.duration)
        from moviepy import ImageClip as IC
        mask_clip = IC(alpha, is_mask=True, duration=clip.duration)
        sub_clip = sub_clip.with_mask(mask_clip)

        return CompositeVideoClip([clip, sub_clip], size=(w, h))
