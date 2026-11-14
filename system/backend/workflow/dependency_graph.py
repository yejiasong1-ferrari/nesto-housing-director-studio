"""Dependency graph — which stages a human edit invalidates.

Stage order mirrors the pipeline in architecture.md:
  vision -> planner -> script -> voice -> timeline -> editing -> rendering

A human edit in the Director Studio never re-runs the whole pipeline.
It only invalidates the stages downstream of the edited layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STAGES = ("vision", "planner", "script", "voice", "timeline", "editing", "rendering")

# change_type -> ordered list of stages that must be recomputed.
# Video render is deferred to explicit "export" — edits only update
# on-disk plan/voice artifacts so the user can iterate freely.
_INVALIDATION_MAP: dict[str, tuple[str, ...]] = {
    # User directly edits narration text for one segment.
    # Script text is user-authored here (no LLM rewrite) -> re-synthesize
    # voice for that one segment. Subtitles follow at export time.
    "script_update": ("voice", "subtitle"),
    # User nudges when narration starts within its own segment window.
    # Script/Voice untouched — persist the offset only until export.
    "audio_offset": ("timeline",),
    # Full 1080p export from current (possibly edited) state.
    "export": ("render_final",),
}


@dataclass
class RevisionPlan:
    """Result of asking the dependency graph what a change invalidates."""

    change_type: str
    segment_id: str
    invalidated: tuple[str, ...] = field(default_factory=tuple)
    preserved: tuple[str, ...] = field(default_factory=tuple)


def plan_revision(change_type: str, segment_id: str = "") -> RevisionPlan:
    """Return the minimal set of stages to recompute for a human edit."""
    invalidated = _INVALIDATION_MAP.get(change_type)
    if invalidated is None:
        raise ValueError(f"Unknown change_type: {change_type!r}")

    known_upstream = {"vision", "planner", "script", "voice", "timeline", "editing"}
    touched = {s for s in invalidated if s in known_upstream}
    preserved = tuple(s for s in STAGES if s not in touched)

    return RevisionPlan(
        change_type=change_type,
        segment_id=segment_id,
        invalidated=invalidated,
        preserved=preserved,
    )
