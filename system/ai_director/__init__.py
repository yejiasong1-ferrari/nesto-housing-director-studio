"""Top-level re-export for ``from ai_director import generate_video``.

Requires ``system/`` on ``sys.path`` (CLI: ``import repo_paths``).
"""

from backend.ai_director import generate_video

__all__ = ["generate_video"]
