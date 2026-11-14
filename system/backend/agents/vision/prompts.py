"""Vision Agent prompt templates and paths.

The Image LLM Analysis module (Module 4) uses its own built-in
system prompt for room analysis. This module provides paths to
additional prompt templates for extended analysis tasks.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "vision"

SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"
ANALYZE_PROMPT_PATH = PROMPTS_DIR / "analyze.md"
ATTENTION_PROMPT_PATH = PROMPTS_DIR / "attention.md"


def load_prompt(path: Path, **kwargs: str) -> str:
    """Load a prompt template and fill in variables."""
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs) if kwargs else template
