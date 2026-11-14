"""Shared utilities for Planner Agent modules."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Reasoning models consume internal tokens; 2048 is often exhausted before JSON output.
PLANNER_LLM_MAX_TOKENS = 4096
PLANNER_INTENT_MAX_TOKENS = 2048


def extract_json(text: str) -> Any:
    """Extract JSON from LLM response text."""
    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
    # strict=False: models routinely leave a raw newline inside a reasoning
    # string. Rejecting the whole payload over that loses a full stage of work.
    return json.loads(cleaned, strict=False)


def safe_extract_json(text: str, fallback: Any = None) -> Any:
    """Parse JSON from LLM response with fallback on failure."""
    if not text or not text.strip():
        logger.warning("LLM returned empty content — likely max_tokens exhausted by reasoning")
        return fallback
    try:
        return extract_json(text)
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        logger.warning("Failed to parse LLM JSON: %s | preview: %s", exc, text[:200])
        return fallback


def coerce_float(value: Any, default: float = 0.0) -> float:
    """Coerce a value to float in [0, 1] range."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, result))


def coerce_str_list(value: Any) -> list[str]:
    """Coerce LLM output to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        return [value]
    return []
