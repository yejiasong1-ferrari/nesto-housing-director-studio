"""User director-intent intake (workflow layer — not an Agent).

Architecture: User → Prompt → ProjectState.user_goal → Planner Intent Interpreter.

Always collect a director prompt before Planner/Script. If the user leaves it
empty or answers vaguely (style-only / too short), expand to the default
space / facilities / lighting coverage prompt.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default when user skips or gives a vague style-only answer.
# Emphasizes space identity, visible facilities, and light — not mood adjectives alone.
DEFAULT_DIRECTOR_PROMPT = (
    "逐一介绍每个空间：这是什么房间、画面中可见的主要设施与家具家电、"
    "空间布局与动线，以及采光与光线感受。语气专业温暖，适合房产展示；"
    "少用空洞氛围词，多说看得见的空间与设施。"
)

DEFAULT_DIRECTOR_PROMPT_EN = (
    "For each space, introduce what room it is, the key facilities / furniture / "
    "appliances visible on screen, the layout and flow, and how the natural light "
    "feels. Warm professional real-estate tone; prefer concrete visible details "
    "over vague mood adjectives."
)

# Signals that the user actually asked for content coverage
_CONTENT_MARKERS = (
    "kitchen", "厨房", "living", "客厅", "bedroom", "卧室", "bathroom", "浴室",
    "卫生间", "studio", "公寓", "room", "房间",
    "light", "采光", "光线", "阳光", "skylight", "window", "窗",
    "space", "空间", "layout", "布局", "动线", "open", "开放",
    "facility", "设施", "furniture", "家具", "appliance", "家电",
    "cabinet", "柜", "counter", "台面", "island", "中岛", "sink", "水槽",
    "range", "灶", "fridge", "冰箱", "shelf", "架",
    "introduce", "介绍", "showcase", "展示", "highlight", "突出",
    "tour", "tour", "walkthrough", "带看",
)

# Style-only words that alone do not specify what to narrate
_STYLE_ONLY_MARKERS = (
    "现代", "高级", "温馨", "简洁", "豪华", "高端", "时尚", "年轻", "都市",
    "luxury", "modern", "minimal", "premium", "cozy", "warm", "bright",
    "chic", "elegant", "stylish", "urban", "young",
)


@dataclass
class ResolvedUserIntent:
    """Result of workflow intent intake."""

    prompt: str
    source: str  # user | default_empty | default_vague | cli
    was_vague: bool = False
    original_prompt: str = ""


def is_vague_prompt(prompt: str) -> bool:
    """True when prompt is empty, tiny, or style-only without content focus."""
    text = (prompt or "").strip()
    if not text:
        return True
    if text.lower() in {"default", "默认", "d", "skip", "无", "随便", "ok", "yes"}:
        return True
    # Very short answers rarely specify coverage
    if len(text) < 10:
        return True

    lower = text.lower()
    has_content = any(m in lower or m in text for m in _CONTENT_MARKERS)
    if has_content:
        return False

    # No content markers → treat as vague (often pure style adjectives)
    style_hits = sum(1 for m in _STYLE_ONLY_MARKERS if m in lower or m in text)
    if style_hits > 0:
        return True

    # Unknown short-ish phrase without content markers
    if len(text) < 24:
        return True
    return False


def resolve_user_intent(
    prompt: str | None,
    *,
    interactive: bool | None = None,
    default_prompt: str | None = None,
    language: str = "zh",
) -> ResolvedUserIntent:
    """Resolve director prompt: ask user when needed; expand vague → default.

    Args:
        prompt: CLI-provided prompt, or None/"" to trigger intake.
        interactive: Force TTY ask. Default: ask only when stdin is a TTY and
            no usable CLI prompt was given.
        default_prompt: Fallback coverage prompt. If None, picks EN/ZH from language.
        language: Narration language code — ``en`` or ``zh`` (default zh for CLI).
    """
    lang = (language or "zh").strip().lower()
    if lang not in ("en", "zh"):
        lang = "zh"
    if default_prompt is None:
        default_prompt = DEFAULT_DIRECTOR_PROMPT_EN if lang == "en" else DEFAULT_DIRECTOR_PROMPT

    cli_prompt = (prompt or "").strip()
    if interactive is None:
        interactive = sys.stdin.isatty() and not cli_prompt

    original = cli_prompt
    if interactive:
        print("\n" + "=" * 64)
        print("  AI Director — 请输入导演意图 / Director intent")
        print("=" * 64)
        print("  说明你希望成片强调什么（空间、设施、采光、受众等）。")
        print("  直接回车，或输入「默认」→ 使用默认：介绍空间 / 设施 / 光线。")
        print("-" * 64)
        try:
            original = input("User prompt: ").strip()
        except EOFError:
            original = ""

    if not original:
        logger.info("Empty user prompt — using default space/facilities/light intent (%s)", lang)
        return ResolvedUserIntent(
            prompt=default_prompt,
            source="default_empty",
            was_vague=True,
            original_prompt="",
        )

    if is_vague_prompt(original):
        logger.info(
            "Vague user prompt %r — expanding to default space/facilities/light intent (%s)",
            original[:80],
            lang,
        )
        print(
            "\n  [intent] 输入较模糊，已改用默认导演意图："
            "介绍空间、可见设施、采光与光线。"
        )
        return ResolvedUserIntent(
            prompt=default_prompt,
            source="default_vague",
            was_vague=True,
            original_prompt=original,
        )

    source = "cli" if cli_prompt and not interactive else "user"
    return ResolvedUserIntent(
        prompt=original,
        source=source,
        was_vague=False,
        original_prompt=original,
    )
