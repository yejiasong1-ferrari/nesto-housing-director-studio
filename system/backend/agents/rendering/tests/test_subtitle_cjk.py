"""Chinese subtitle burn must use a CJK-capable font (not blank glyphs)."""

from __future__ import annotations

import numpy as np

from backend.agents.rendering.processors.subtitle_processor import (
    _contains_cjk,
    _load_font,
    _make_subtitle_image,
    _wrap_by_pixel_width,
)


def test_contains_cjk_detects_chinese() -> None:
    assert _contains_cjk("厨房采光很好")
    assert not _contains_cjk("Bright kitchen light")


def test_cjk_font_loads_on_this_machine() -> None:
    font = _load_font(30, "厨房采光很好")
    assert font is not None
    # Default bitmap font has no .path / fails size checks differently —
    # at minimum ensure TrueType-like font with getbbox / getsize support.
    assert hasattr(font, "getbbox") or hasattr(font, "getmask")


def test_chinese_subtitle_image_has_visible_glyphs() -> None:
    arr = _make_subtitle_image("厨房采光很好，家具齐全。", 1280, 720)
    assert arr.shape == (720, 1280, 4)
    # Look at lower bar region for non-transparent bright pixels
    bar = arr[560:, :, :]
    opaque = bar[:, :, 3] > 100
    bright = bar[:, :, 0] > 180
    visible_white = int(np.sum(opaque & bright))
    assert visible_white > 200, f"expected Chinese glyphs, got {visible_white} white pixels"


def test_long_chinese_keeps_three_lines() -> None:
    """Bar used to cap at 140px (2 lines); long wrap must still show line 3."""
    from PIL import Image, ImageDraw

    from backend.agents.rendering.processors.subtitle_processor import (
        FIXED_FONT_SIZE,
        MIN_SIDE_MARGIN_PX,
        SIDE_MARGIN_RATIO,
    )

    text = (
        "卧室中这张双人床配黑色软包床头与灰色床品，"
        "落地推拉门引出开阔城市景观，采光充足适合居住，"
        "晨起即可看见窗外绿意与城市轮廓。"
    )
    width, height = 1080, 1920
    arr = _make_subtitle_image(text, width, height)
    side = max(MIN_SIDE_MARGIN_PX, int(width * SIDE_MARGIN_RATIO))
    font = _load_font(FIXED_FONT_SIZE, text)
    measure = Image.new("RGBA", (width, 64), (0, 0, 0, 0))
    lines = _wrap_by_pixel_width(
        ImageDraw.Draw(measure), text, font, width - 2 * side
    )
    assert len(lines) >= 3

    opaque = arr[:, :, 3] > 100
    bright = arr[:, :, 0] > 180
    rows = np.where((opaque & bright).any(axis=1))[0]
    assert rows.size > 0
    span = int(rows.max() - rows.min())
    assert span >= 90, f"glyph span {span}px too short for 3 subtitle lines"


def test_chinese_wraps_by_character() -> None:
    from PIL import Image, ImageDraw

    font = _load_font(30, "厨房采光很好")
    measure = Image.new("RGBA", (400, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(measure)
    lines = _wrap_by_pixel_width(draw, "厨房采光很好家具齐全自然通透非常适合居住", font, 120)
    assert len(lines) >= 2


def test_default_subtitle_sits_above_source_caption_band() -> None:
    arr = _make_subtitle_image("厨房采光很好，家具齐全。", 1280, 720)
    alpha_rows = np.where((arr[:, :, 3] > 100).any(axis=1))[0]
    assert alpha_rows.size > 0
    # Keep generated captions out of the lowest source-label strip.
    assert int(alpha_rows.max()) <= 720 - 70
