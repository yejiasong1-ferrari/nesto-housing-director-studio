"""Measured TTS speaking rates for narration budgets.

Chinese (Volcengine 温暖阿虎, eval-agent-8, n=12):
  mean 4.17 chars/sec, median 4.28 → budget 4.2

English (Volcengine M392 conversation, 5 agent-tour lines at speed=1.0):
  typical 2.29–2.56 words/sec, median 2.48, one outlier 3.46.
  Budget 2.3 wps (138 wpm) — slightly slower than the median so the LLM
  writes fewer words than TTS will actually speak. Over-budgeting is what
  forced 0.23–0.43× slow-motion on earlier English/Chinese finals.
"""

from __future__ import annotations

import re

ZH_CHARS_PER_SECOND = 4.2
EN_WORDS_PER_SECOND = 2.3
EN_WORDS_PER_MINUTE = round(EN_WORDS_PER_SECOND * 60)  # 138

# How far a shot may be slowed to cover its narration. Beyond this the picture
# visibly drags — a 4s counter-top shot held for 8s looks like padding.
MAX_PICTURE_STRETCH = 1.35

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def is_zh(language: str | None) -> bool:
    return (language or "en").strip().lower() == "zh"


def count_units(text: str, language: str | None = "en") -> int:
    """Characters for zh, whitespace/token words for en."""
    if not text:
        return 0
    if is_zh(language):
        return len(text.replace(" ", ""))
    return len(_WORD_RE.findall(text)) or len(text.split())


def estimated_duration(text: str, language: str | None = "en") -> float:
    units = count_units(text, language)
    if units <= 0:
        return 0.0
    rate = ZH_CHARS_PER_SECOND if is_zh(language) else EN_WORDS_PER_SECOND
    return round(units / rate, 2)


def speakable_window(
    editing_window: float,
    source_duration: float,
    *,
    pad: float = 0.0,
    floor: float = 1.5,
) -> float:
    """Seconds of speech a shot can carry without dragging the picture.

    ``editing_window`` already contains whatever stretch an earlier pass
    granted to fit a long draft. Budgeting from it feeds back on itself: a
    long line stretches the shot, the wider window permits a longer line.
    Anchor the budget to the real footage instead.
    """
    window = max(0.0, float(editing_window or 0.0))
    source = max(0.0, float(source_duration or 0.0))
    if source > 0:
        window = min(window, source * MAX_PICTURE_STRETCH) if window else source
    return max(floor, window - max(0.0, pad))


def word_budget(
    duration_seconds: float,
    language: str | None = "en",
    *,
    fill_ratio: float = 1.0,
    min_units: int | None = None,
    max_units: int | None = None,
) -> int:
    """Maximum speakable units that fit in ``duration_seconds`` of footage."""
    duration = max(float(duration_seconds or 0.0), 0.1)
    if is_zh(language):
        rate = ZH_CHARS_PER_SECOND
        floor = 18 if min_units is None else min_units
    else:
        rate = EN_WORDS_PER_SECOND
        floor = 8 if min_units is None else min_units
    budget = max(floor, int(round(duration * rate * fill_ratio)))
    if max_units is not None:
        budget = min(budget, max_units)
    return budget
