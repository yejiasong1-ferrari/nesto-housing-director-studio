"""Base agent interface for all cognitive agents.

Every agent in the AI Director system inherits from BaseAgent and implements
a single cognitive responsibility. Agents communicate exclusively through
ProjectState, reading inputs from other agents' state fields and writing
only to their own state field.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from backend.state.project_state import ProjectState


logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all AI Director agents.

    Each agent has exactly one cognitive responsibility. It reads the
    ProjectState, performs its reasoning, and writes results back to
    its own state field. It must never modify another agent's state.
    """

    agent_name: str = "base"
    state_key: str = "base"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = logging.getLogger(f"backend.agents.{self.agent_name}")

    @abstractmethod
    async def run(self, state: ProjectState) -> ProjectState:
        """Execute the agent's cognitive task.

        Args:
            state: The current shared project state.

        Returns:
            Updated project state with this agent's output written
            to its own state field.
        """
        ...

    def read_state(self, state: ProjectState) -> dict[str, Any]:
        """Read this agent's state field from the shared project state."""
        return getattr(state, self.state_key, {}) or {}

    def write_state(self, state: ProjectState, data: dict[str, Any]) -> ProjectState:
        """Write data to this agent's state field in the shared project state.

        This is the only way an agent should modify ProjectState.
        """
        state_dict = state.model_dump()
        state_dict[self.state_key] = data
        return ProjectState(**state_dict)

    async def execute(self, state: ProjectState) -> ProjectState:
        """Run the agent with logging and error handling.

        This is the entry point called by the WorkflowEngine.
        """
        self.logger.info(f"Agent [{self.agent_name}] starting execution")
        try:
            result = await self.run(state)
            self.logger.info(f"Agent [{self.agent_name}] completed successfully")
            return result
        except Exception as e:
            self.logger.error(f"Agent [{self.agent_name}] failed: {e}", exc_info=True)
            raise
