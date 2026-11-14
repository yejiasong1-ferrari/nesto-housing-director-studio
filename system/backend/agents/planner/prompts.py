"""Planner Agent prompt templates."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "planner"

SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"
INTENT_PROMPT_PATH = PROMPTS_DIR / "intent.md"
NARRATIVE_PROMPT_PATH = PROMPTS_DIR / "narrative.md"
CINEMATIC_PROMPT_PATH = PROMPTS_DIR / "cinematic.md"

# Legacy paths (deprecated)
ATTENTION_PROMPT_PATH = PROMPTS_DIR / "attention.md"
REASONING_PROMPT_PATH = PROMPTS_DIR / "reasoning.md"
STRATEGY_PROMPT_PATH = PROMPTS_DIR / "strategy.md"
PLAN_PROMPT_PATH = PROMPTS_DIR / "plan.md"


def load_prompt(path: Path, **kwargs: str) -> str:
    """Load and optionally format a prompt template."""
    template = path.read_text(encoding="utf-8")
    if kwargs:
        return template.format(**kwargs)
    return template
