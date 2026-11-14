"""Rendering Agent — deterministic execution engine.

Converts EditingPlan + source video into final MP4.
This agent has NO reasoning. It is pure deterministic execution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.agents.rendering.render_service import RenderService
from backend.core.base_agent import BaseAgent
from backend.schemas.editing_schema import EditingPlan
from backend.state.project_state import ProjectState

logger = logging.getLogger(__name__)


class RenderingAgent(BaseAgent):
    """Deterministic execution: EditingPlan + video source → MP4."""

    agent_name = "rendering"
    state_key = "render"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        source_video_path: str | None = None,
        output_path: str | None = None,
        output_width: int = 1920,
        output_height: int = 1080,
        fps: int = 30,
    ) -> None:
        super().__init__(config)
        self.source_video_path = source_video_path
        self.output_path = output_path
        preserve = bool((config or {}).get("preserve_full_span", True))
        self.renderer = RenderService(
            output_width,
            output_height,
            fps,
            preserve_full_span=preserve,
        )

    async def run(self, state: ProjectState) -> ProjectState:
        editing_data = state.editing or {}
        if not editing_data.get("segments"):
            raise ValueError("EditingPlan is required but segments is empty")

        source = self.source_video_path
        if not source:
            raise ValueError("source_video_path must be set on RenderingAgent")

        output = self.output_path
        if not output:
            raise ValueError("output_path must be set on RenderingAgent")

        editing_plan = EditingPlan.model_validate(editing_data)
        audio_config = state.audio_config
        bgm = audio_config.background_music
        logger.info(
            "RenderingAgent: %d segments | source=%s → %s | bgm=%s (%.0fdB)",
            len(editing_plan.segments),
            Path(source).name,
            Path(output).name,
            "on" if bgm.enabled else "off",
            bgm.volume_db,
        )

        result = self.renderer.render(
            source, editing_plan, output, audio_config=audio_config,
        )
        return self.write_state(state, result.model_dump(mode="json"))
