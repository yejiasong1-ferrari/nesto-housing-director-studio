"""Workflow engine for orchestrating the AI Director agent pipeline.

The WorkflowEngine manages the sequential execution of all cognitive agents,
handles the quality feedback loop, and tracks pipeline status.

Data flow:
    Vision -> Content Planner -> Script -> Voice -> Timeline Optimization
    -> Editing Strategy -> Rendering -> Quality Evaluation
    -> (if failed) back to Timeline Optimization
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.base_agent import BaseAgent
from backend.state.project_state import ProjectState


logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Orchestrates the agent pipeline with feedback loop support.

    The engine executes agents in sequence, passing ProjectState between
    them. If the Quality Evaluation Agent rejects the output, the engine
    loops back to the Timeline Optimization Agent for refinement.
    """

    def __init__(
        self,
        agents: list[BaseAgent] | None = None,
        max_feedback_loops: int = 3,
        feedback_start_index: int = 4,
    ) -> None:
        """Initialize the workflow engine.

        Args:
            agents: Ordered list of agents to execute.
            max_feedback_loops: Maximum number of feedback loop iterations.
            feedback_start_index: Index of the Timeline Optimization Agent
                in the agents list (loop back target on evaluation failure).
        """
        self.agents: list[BaseAgent] = agents or []
        self.max_feedback_loops = max_feedback_loops
        self.feedback_start_index = feedback_start_index

    def register_agent(self, agent: BaseAgent) -> None:
        """Add an agent to the pipeline."""
        self.agents.append(agent)
        logger.info(f"Registered agent: {agent.agent_name}")

    def register_agents(self, agents: list[BaseAgent]) -> None:
        """Add multiple agents to the pipeline."""
        for agent in agents:
            self.register_agent(agent)

    async def run(self, state: ProjectState) -> ProjectState:
        """Execute the full production pipeline.

        Runs all agents in sequence. If the evaluation agent
        reports failure, loops back to the timeline optimization
        agent for refinement (up to max_feedback_loops times).

        Args:
            state: Initial project state.

        Returns:
            Final project state after all agents have executed.
        """
        current_state = state
        feedback_loops = 0

        while feedback_loops <= self.max_feedback_loops:
            start_idx = self.feedback_start_index if feedback_loops > 0 else 0

            for i in range(start_idx, len(self.agents)):
                agent = self.agents[i]
                current_state = current_state.model_copy(
                    update={"current_agent": agent.agent_name, "pipeline_status": "running"}
                )
                logger.info(
                    f"Pipeline step {i + 1}/{len(self.agents)}: "
                    f"{agent.agent_name} (loop {feedback_loops})"
                )

                current_state = await agent.execute(current_state)

            evaluation = current_state.evaluation or {}
            passed = evaluation.get("passed", False)

            if passed:
                current_state = current_state.model_copy(
                    update={"pipeline_status": "completed", "current_agent": ""}
                )
                logger.info("Pipeline completed successfully")
                return current_state

            feedback_loops += 1
            logger.warning(
                f"Quality evaluation failed (loop {feedback_loops}/{self.max_feedback_loops})"
            )

        current_state = current_state.model_copy(
            update={"pipeline_status": "failed", "current_agent": ""}
        )
        logger.error(
            f"Pipeline failed after {self.max_feedback_loops} feedback loops"
        )
        return current_state

    def get_pipeline_info(self) -> dict[str, Any]:
        """Return information about the configured pipeline."""
        return {
            "agents": [agent.agent_name for agent in self.agents],
            "max_feedback_loops": self.max_feedback_loops,
            "feedback_start_index": self.feedback_start_index,
        }
