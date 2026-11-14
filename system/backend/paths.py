"""Canonical filesystem roots after the ``system/`` layout move.

Layout::

    <repo>/
      .env
      storage/
      system/
        backend/   ← this package
        frontend/
        ...
"""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
SYSTEM_ROOT = BACKEND_ROOT.parent
REPO_ROOT = SYSTEM_ROOT.parent
