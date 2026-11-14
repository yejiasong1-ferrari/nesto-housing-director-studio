"""Rendering Agent - Execution Layer.

Executes deterministic media operations based on Timeline and
Editing Strategy. NEVER calls LLM. NEVER performs reasoning.
Only executes using FFmpeg, MoviePy, and OpenCV.
"""

from backend.agents.rendering.agent import RenderingAgent

__all__ = ["RenderingAgent"]
