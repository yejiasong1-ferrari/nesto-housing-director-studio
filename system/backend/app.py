"""Backward-compatible entrypoint.

Prefer::

    uvicorn backend.main:app --reload

``uvicorn backend.app:app`` still works (same FastAPI app).
"""

from backend.main import app

__all__ = ["app"]
