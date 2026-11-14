"""Vision Agent - Spatial Perception Engine.

The sole perception module of the AI Director system.
Transforms walkthrough video into a Vision Knowledge Base (VKB)
that all downstream agents consume.

Principle: Perceive Once, Reuse Everywhere.
"""

from backend.agents.vision.agent import VisionAgent

__all__ = ["VisionAgent"]
