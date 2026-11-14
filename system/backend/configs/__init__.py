"""Agent configuration package."""

from backend.configs.loader import (
    agent_section,
    continuous_walkthrough_enabled,
    load_agents_config,
    preserve_full_span_enabled,
)

__all__ = [
    "agent_section",
    "continuous_walkthrough_enabled",
    "load_agents_config",
    "preserve_full_span_enabled",
]
