"""Contrastive score normalization and role band assignment.

After raw attention scores are computed, stretch scores into HERO / SUPPORT /
TRANSITION bands to enforce hierarchical differentiation.
"""

from __future__ import annotations

import logging
import math
import statistics

from backend.schemas.planning_schema import AttentionEntry

logger = logging.getLogger(__name__)

ROLE_HERO = "HERO"
ROLE_SUPPORT = "SUPPORT"
ROLE_TRANSITION = "TRANSITION"

HERO_SCORE_RANGE = (0.85, 0.98)
SUPPORT_SCORE_RANGE = (0.48, 0.78)
TRANSITION_SCORE_RANGE = (0.15, 0.42)

DEFAULT_MIN_HERO = 2
DEFAULT_HERO_FRACTION = 0.15
DEFAULT_TRANSITION_FRACTION = 0.30
MIN_SCORE_STDDEV = 0.12


def _linear_stretch(values: list[float], low: float, high: float) -> list[float]:
    """Stretch values to [low, high] preserving relative order."""
    if not values:
        return []
    if len(values) == 1:
        return [round((low + high) / 2, 3)]

    vmin, vmax = min(values), max(values)
    if vmax - vmin < 1e-6:
        mid = (low + high) / 2
        return [round(mid, 3) for _ in values]

    return [
        round(low + (v - vmin) / (vmax - vmin) * (high - low), 3)
        for v in values
    ]


def _global_restretch(entries: list[AttentionEntry]) -> None:
    """Re-stretch all scores globally when band contrast is insufficient."""
    scores = [e.score for e in entries]
    stretched = _linear_stretch(scores, 0.15, 0.98)
    for entry, score in zip(entries, stretched):
        entry.score = score


def contrastive_normalize(
    entries: list[AttentionEntry],
    min_hero_segments: int = DEFAULT_MIN_HERO,
    hero_top_fraction: float = DEFAULT_HERO_FRACTION,
    transition_bottom_fraction: float = DEFAULT_TRANSITION_FRACTION,
) -> list[AttentionEntry]:
    """Apply contrastive normalization and assign HERO/SUPPORT/TRANSITION roles."""
    if not entries:
        return entries

    n = len(entries)
    sorted_entries = sorted(entries, key=lambda e: e.score, reverse=True)

    hero_count = min(n, max(min_hero_segments, math.ceil(n * hero_top_fraction)))
    transition_count = min(n - hero_count, math.ceil(n * transition_bottom_fraction))

    hero_entries = sorted_entries[:hero_count]
    transition_entries = sorted_entries[n - transition_count:] if transition_count else []
    transition_ids = {e.segment_id for e in transition_entries} - {e.segment_id for e in hero_entries}
    hero_ids = {e.segment_id for e in hero_entries}
    support_entries = [
        e for e in sorted_entries
        if e.segment_id not in hero_ids and e.segment_id not in transition_ids
    ]

    _apply_band_scores(hero_entries, HERO_SCORE_RANGE, ROLE_HERO)
    _apply_band_scores(support_entries, SUPPORT_SCORE_RANGE, ROLE_SUPPORT)
    _apply_band_scores(
        [e for e in entries if e.segment_id in transition_ids],
        TRANSITION_SCORE_RANGE,
        ROLE_TRANSITION,
    )

    if n >= 3:
        stddev = statistics.pstdev([e.score for e in entries])
        score_range = max(e.score for e in entries) - min(e.score for e in entries)
        if stddev < MIN_SCORE_STDDEV or score_range < 0.50:
            logger.warning(
                "Insufficient score contrast (std=%.3f, range=%.3f); re-stretching",
                stddev,
                score_range,
            )
            _global_restretch(entries)
            _reapply_roles_after_restretch(
                entries,
                hero_count,
                transition_count,
            )

    return sorted(entries, key=lambda e: e.score, reverse=True)


def _apply_band_scores(
    band_entries: list[AttentionEntry],
    score_range: tuple[float, float],
    role: str,
) -> None:
    raw_scores = [e.score for e in band_entries]
    stretched = _linear_stretch(raw_scores, score_range[0], score_range[1])
    for entry, score in zip(band_entries, stretched):
        entry.score = score
        entry.role = role


def _reapply_roles_after_restretch(
    entries: list[AttentionEntry],
    hero_count: int,
    transition_count: int,
) -> None:
    sorted_entries = sorted(entries, key=lambda e: e.score, reverse=True)
    n = len(entries)
    hero_ids = {e.segment_id for e in sorted_entries[:hero_count]}
    transition_ids = {
        e.segment_id for e in sorted_entries[n - transition_count:]
    } - hero_ids if transition_count else set()

    for entry in entries:
        if entry.segment_id in hero_ids:
            entry.role = ROLE_HERO
        elif entry.segment_id in transition_ids:
            entry.role = ROLE_TRANSITION
        else:
            entry.role = ROLE_SUPPORT
