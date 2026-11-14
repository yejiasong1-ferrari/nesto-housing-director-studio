"""Tests for the Rendering Agent (non-video unit tests)."""

import pytest

from backend.agents.rendering.agent import RenderingAgent
from backend.state.project_state import ProjectState


def test_rendering_agent_state_key() -> None:
    assert RenderingAgent().state_key == "render"


def test_rendering_agent_no_llm() -> None:
    """Rendering agent must not have any LLM provider dependency."""
    agent = RenderingAgent()
    assert not hasattr(agent, "llm_provider")


@pytest.mark.asyncio
async def test_rendering_agent_raises_without_source() -> None:
    state = ProjectState(
        project_id="test",
        editing={"agent_name": "editing", "segments": [{"segment_id": "s1"}]},
    )
    agent = RenderingAgent()  # no source_video_path
    with pytest.raises(ValueError, match="source_video_path"):
        await agent.run(state)


@pytest.mark.asyncio
async def test_rendering_agent_raises_without_editing() -> None:
    state = ProjectState(project_id="test", editing={})
    agent = RenderingAgent(source_video_path="fake.mov", output_path="/tmp/out.mp4")
    with pytest.raises(ValueError, match="EditingPlan"):
        await agent.run(state)
