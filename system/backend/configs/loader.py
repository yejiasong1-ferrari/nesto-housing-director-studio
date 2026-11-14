"""Load agent section configs from backend/configs/agents.yaml.

Studio / CLI / orchestrator should all read the same knobs so continuous
walkthrough behaviour is consistent on the web path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent / "agents.yaml"


@lru_cache(maxsize=1)
def load_agents_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    data = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def agent_section(name: str) -> dict[str, Any]:
    section = load_agents_config().get(name) or {}
    return dict(section) if isinstance(section, dict) else {}


def continuous_walkthrough_enabled() -> bool:
    timeline = agent_section("timeline")
    return bool(timeline.get("continuous_walkthrough", True))


def preserve_full_span_enabled() -> bool:
    rendering = agent_section("rendering")
    return bool(rendering.get("preserve_full_span", True))
