"""Shared Project State for all agents.

ProjectState is the central communication medium for the AI Director system.
Every agent reads from and writes to this shared state. Each agent owns
exactly one state field and must never modify another agent's field.

This design ensures:
- Loose coupling between agents
- Reproducibility of the production pipeline
- Traceability of every decision
- Debuggability of the entire workflow
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.audio_schema import AudioConfig


class UserGoal(BaseModel):
    """User's input and intent for the production."""

    prompt: str = ""
    property_metadata: dict[str, Any] = Field(default_factory=dict)


class VideoMetadata(BaseModel):
    """Technical metadata about the source video."""

    file_path: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    file_size: int = 0


class ProjectState(BaseModel):
    """Central shared state for the entire production pipeline.

    Each agent owns exactly one field. Agents read from other fields
    but write only to their own.

    audio_config is workflow config (like resolution/fps), not Agent-owned.
    Rendering reads it; no Agent decides BGM selection in V1.
    """

    project_id: str = ""
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    user_goal: UserGoal = Field(default_factory=UserGoal)
    video_metadata: VideoMetadata = Field(default_factory=VideoMetadata)

    # Workflow media config — fixed BGM path/volume (not an Agent decision)
    audio_config: AudioConfig = Field(default_factory=AudioConfig)

    vision: dict[str, Any] = Field(default_factory=dict)
    planning: dict[str, Any] = Field(default_factory=dict)
    script: dict[str, Any] = Field(default_factory=dict)
    voice: dict[str, Any] = Field(default_factory=dict)
    timeline: dict[str, Any] = Field(default_factory=dict)
    editing: dict[str, Any] = Field(default_factory=dict)
    render: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)

    pipeline_status: str = "initialized"
    current_agent: str = ""


class StateManager:
    """Manages read/write access to ProjectState with per-agent isolation.

    Provides a controlled interface for agents to access the shared state,
    ensuring each agent only modifies its own state field.
    """

    def __init__(self, state: ProjectState) -> None:
        self._state = state

    @property
    def state(self) -> ProjectState:
        """Get the current project state (read-only access)."""
        return self._state

    def read(self, key: str) -> dict[str, Any]:
        """Read a state field by key.

        Args:
            key: The state field name (e.g. 'vision', 'planning').

        Returns:
            The state data for that field, or empty dict if not set.
        """
        return getattr(self._state, key, {}) or {}

    def write(self, key: str, data: dict[str, Any]) -> ProjectState:
        """Write data to a state field.

        Args:
            key: The state field name.
            data: The data to write.

        Returns:
            Updated ProjectState instance.
        """
        from datetime import datetime, timezone

        state_dict = self._state.model_dump()
        state_dict[key] = data
        state_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._state = ProjectState(**state_dict)
        return self._state

    def update_pipeline_status(self, status: str, current_agent: str = "") -> ProjectState:
        """Update the pipeline execution status."""
        state_dict = self._state.model_dump()
        state_dict["pipeline_status"] = status
        state_dict["current_agent"] = current_agent
        self._state = ProjectState(**state_dict)
        return self._state
