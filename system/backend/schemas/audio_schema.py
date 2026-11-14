"""Workflow audio config — fixed media resources, not Agent decisions.

V1: one default BGM mixed under narration at render time.
No Music Agent / LLM selection.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

# Repo-relative default (resolved against project root at runtime)
DEFAULT_BGM_RELATIVE = "storage/audio/bgm/default_bgm.mp3"
# Matches the level produced by the evaluation feedback loop. Starting at the
# accepted level avoids a redundant second pass on otherwise-approved videos.
DEFAULT_BGM_VOLUME_DB = -18.0
DEFAULT_BGM_FADE_IN = 2.0
DEFAULT_BGM_FADE_OUT = 3.0


def project_root() -> Path:
    """Repo root (``storage/`` lives here, outside ``system/``)."""
    from backend.paths import REPO_ROOT

    return REPO_ROOT


def resolve_bgm_path(path: str | Path | None = None) -> Path:
    """Resolve BGM path; relative paths are against project root."""
    raw = Path(path) if path else Path(DEFAULT_BGM_RELATIVE)
    if raw.is_absolute():
        return raw
    return (project_root() / raw).resolve()


class BackgroundMusicConfig(BaseModel):
    """Fixed background music layer for Rendering AudioMixer."""

    enabled: bool = True
    path: str = DEFAULT_BGM_RELATIVE
    volume_db: float = DEFAULT_BGM_VOLUME_DB
    loop: bool = True
    fade_in: float = DEFAULT_BGM_FADE_IN
    fade_out: float = DEFAULT_BGM_FADE_OUT


class AudioConfig(BaseModel):
    """Workflow-level audio settings (like resolution/fps — not Agent-owned)."""

    background_music: BackgroundMusicConfig = Field(
        default_factory=BackgroundMusicConfig
    )

    def resolved_bgm_path(self) -> Path:
        return resolve_bgm_path(self.background_music.path)
