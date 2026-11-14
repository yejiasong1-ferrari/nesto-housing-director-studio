"""Voice Agent prompt templates."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"

SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"


def load_prompt(path: Path, **kwargs: str) -> str:
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs) if kwargs else template
