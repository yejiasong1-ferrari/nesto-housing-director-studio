"""Shared LLM endpoint defaults (Aliyun MaaS Qwen-VL, OpenAI-compatible)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# repo root: system/backend/services/llm/config.py → parents[4]
_REPO_ROOT = Path(__file__).resolve().parents[4]
# Project .env wins over stale shell exports (e.g. old local gateway URL).
load_dotenv(_REPO_ROOT / ".env", override=True)

# Aliyun MaaS workspace: nesto-ai-director
DEFAULT_OPENAI_BASE_URL = (
    "https://llm-us3whhqdyc0mhmso.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
DEFAULT_OPENAI_MODEL = "qwen3-vl-plus"


def openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def openai_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).strip()


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
