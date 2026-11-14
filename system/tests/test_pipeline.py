#!/usr/bin/env python3
"""Phase 1 smoke: call generate_video() as a Python API (not via CLI only).

Requires LLM + VOLCENGINE_API_KEY (same as run_v3_final).

    python tests/test_pipeline.py
    python tests/test_pipeline.py --video ./4.mp4 --language zh --brief "多介绍采光"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# system/tests → parents[2] = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_ROOT = REPO_ROOT / "system"
for _p in (SYSTEM_ROOT, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ai_director import generate_video  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1: generate_video() facade smoke test")
    parser.add_argument(
        "--video",
        default=str(REPO_ROOT / "4.mp4"),
        help="Walkthrough video path",
    )
    parser.add_argument(
        "--brief",
        default=(
            "Highlight: modern kitchen, natural light, spacious living room"
        ),
        help="Director brief",
    )
    parser.add_argument(
        "--language",
        default="English",
        help="Narration language (en/zh/English/Chinese)",
    )
    args = parser.parse_args()

    output = await generate_video(
        video_path=args.video,
        brief=args.brief,
        language=args.language,
    )
    print("Generated:", output)


if __name__ == "__main__":
    asyncio.run(main())
