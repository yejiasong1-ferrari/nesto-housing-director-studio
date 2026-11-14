"""Script Agent prompt templates."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "script"

SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"
NARRATOR_PROMPT_PATH = PROMPTS_DIR / "narrator.md"
REWRITE_PROMPT_PATH = PROMPTS_DIR / "rewrite.md"

# Reference-only documents (deterministic rule-based modules; not sent to any LLM)
PLANNER_DOC_PATH = PROMPTS_DIR / "planner.md"
STYLE_DOC_PATH = PROMPTS_DIR / "style.md"

# Legacy path (deprecated, kept for backward compatibility)
NARRATE_PROMPT_PATH = PROMPTS_DIR / "narrate.md"


def load_prompt(path: Path, **kwargs: str) -> str:
    """Load and optionally format a prompt template."""
    template = path.read_text(encoding="utf-8")
    if kwargs:
        return template.format(**kwargs)
    return template
