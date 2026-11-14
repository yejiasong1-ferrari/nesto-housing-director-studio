"""Put ``system/`` on ``sys.path`` so ``import backend`` / ``import ai_director`` work.

CLI scripts at the repo root should::

    import repo_paths  # noqa: F401
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SYSTEM_ROOT = REPO_ROOT / "system"

for _p in (SYSTEM_ROOT, REPO_ROOT):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)
