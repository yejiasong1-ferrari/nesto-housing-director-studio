"""Abstract LLM provider interface.

All LLM providers must implement this interface. The system supports
multiple LLM providers without changing the cognitive workflow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class LLMMessage(BaseModel):
    """A single message in an LLM conversation."""

    role: str  # system, user, assistant
    content: str


class LLMResponse(BaseModel):
    """Response from an LLM provider."""

    content: str
    model: str = ""
    usage: dict[str, int] = {}
    finish_reason: str = ""


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Every LLM provider must implement generate() and generate_structured().
    This abstraction allows the system to swap between OpenAI, Anthropic,
    or other providers without changing agent logic.
    """

    provider_name: str = "base"

    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a text response from the LLM.

        Args:
            messages: Conversation messages.
            model: Model identifier (provider-specific).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMResponse with generated content.
        """
        ...

    @abstractmethod
    async def generate_structured(
        self,
        messages: list[LLMMessage],
        response_schema: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a structured JSON response from the LLM.

        Args:
            messages: Conversation messages.
            response_schema: JSON schema for the expected response.
            model: Model identifier.
            temperature: Sampling temperature (lower for structured output).
            **kwargs: Additional provider-specific parameters.

        Returns:
            Dictionary matching the response_schema.
        """
        ...
