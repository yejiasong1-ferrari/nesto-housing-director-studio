"""AI Director public Python API.

Usage::

    from backend.ai_director import generate_video

    path = await generate_video("house.mov", "Highlight the kitchen", "en")
"""

from backend.ai_director.pipeline import generate_video

__all__ = ["generate_video"]
