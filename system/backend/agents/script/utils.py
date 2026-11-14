"""Shared utilities for Script Agent modules.

Self-contained (does not import from other agent packages) so the
Script Agent remains an independent package per cursor.md.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Reasoning models consume internal tokens before emitting JSON.
# Per-batch output budget: ~30 tokens per scene × batch_size (5) = ~150 tokens output,
# but reasoning overhead can easily eat 3000–6000 tokens, so keep generous headroom.
SCRIPT_LLM_MAX_TOKENS = 8192

# Number of scenes per LLM batch — keeps each call within context/reasoning budget.
SCRIPT_LLM_BATCH_SIZE = 5


def extract_json(text: str) -> Any:
    """Extract JSON from LLM response text, tolerating markdown code fences."""
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


def coerce_str(value: Any, default: str = "") -> str:
    """Coerce a value to a stripped string."""
    if value is None:
        return default
    return str(value).strip()


DANGLING_CONNECTORS = {
    "featuring", "complete", "including", "with", "and", "a", "an", "the",
    "of", "in", "on", "at", "to", "for",
}


def strip_dangling_connectors(words: list[str], max_pops: int = 4) -> list[str]:
    """Drop trailing connector/preposition words left over after hard trimming.

    Prevents word-budget truncation from producing sentences that dangle on
    a bare connector (e.g. "...a warm kitchen, featuring." -> "...a warm kitchen.").
    """
    result = list(words)
    pops = 0
    while result and pops < max_pops:
        last = result[-1].strip(",.;").lower()
        if last in DANGLING_CONNECTORS and len(result) > 1:
            result.pop()
            pops += 1
        else:
            break
    return result


def clause_aware_trim(text: str, limit: int) -> str:
    """Trim text to `limit` words, preferring whole comma-separated clauses.

    Falls back to a hard word-count cut (with dangling-connector cleanup)
    when even the first clause exceeds the budget.
    """
    words = text.split()
    if len(words) <= limit:
        return text

    clauses = [c.strip() for c in text.rstrip(".").split(",") if c.strip()]
    assembled: list[str] = []
    word_count = 0
    for clause in clauses:
        clause_word_count = len(clause.split())
        if word_count + clause_word_count > limit:
            break
        assembled.append(clause)
        word_count += clause_word_count

    if assembled:
        result_words = ", ".join(assembled).split()
    else:
        result_words = words[:limit]

    result_words = strip_dangling_connectors(result_words) or words[:limit]
    trimmed = " ".join(result_words).rstrip(",.;")
    return trimmed + "."


DANGLING_CONNECTORS_ZH = (
    "并", "与", "和", "及", "配", "搭配", "以及", "还有", "同时", "让", "使",
)


def clause_aware_trim_zh(text: str, limit: int) -> str:
    """Trim Chinese text to roughly `limit` characters at clause boundaries."""
    cleaned = text.strip()
    if len(cleaned.replace(" ", "")) <= limit:
        return cleaned if cleaned.endswith(("。", "！", "？")) else cleaned.rstrip("，、；") + "。"

    # Prefer ending at ，。；
    best = ""
    for i, ch in enumerate(cleaned):
        if i + 1 > limit:
            break
        chunk = cleaned[: i + 1]
        if ch in "，。；、":
            best = chunk
    if best:
        trimmed = best.rstrip("，、；")
    else:
        trimmed = cleaned[:limit].rstrip("，、； ")

    for conn in DANGLING_CONNECTORS_ZH:
        if trimmed.endswith(conn):
            trimmed = trimmed[: -len(conn)].rstrip("，、； ")
            break

    if not trimmed:
        trimmed = cleaned[: max(1, limit)]
    return trimmed + ("。" if not trimmed.endswith(("。", "！", "？")) else "")
