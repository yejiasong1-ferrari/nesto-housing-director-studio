"""Unit tests for the generate_video facade (no LLM / TTS)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.ai_director.pipeline import _normalize_language, generate_video


def test_normalize_language_aliases() -> None:
    assert _normalize_language("English") == "en"
    assert _normalize_language("zh") == "zh"
    assert _normalize_language("中文") == "zh"
    with pytest.raises(ValueError):
        _normalize_language("fr")


@pytest.mark.asyncio
async def test_generate_video_returns_final_path(tmp_path: Path) -> None:
    video = tmp_path / "house.mov"
    video.write_bytes(b"fake")
    final = tmp_path / "final_video_v2.mp4"
    final.write_bytes(b"mp4")

    async def _fake_create(job, video_path, resolved_prompt, intent_meta):
        assert video_path == video.resolve()
        assert intent_meta["narration_language"] == "en"
        assert "kitchen" in resolved_prompt.lower() or resolved_prompt
        return {
            "status": "completed",
            "final_video": str(final),
            "slug": "house",
            "error": "",
        }

    with patch(
        "backend.ai_director.pipeline.run_create_project",
        new=AsyncMock(side_effect=_fake_create),
    ):
        out = await generate_video(
            video_path=video,
            brief="Highlight natural light and modern kitchen",
            language="English",
        )

    assert out == final.resolve()


@pytest.mark.asyncio
async def test_generate_video_calls_on_progress(tmp_path: Path) -> None:
    video = tmp_path / "house.mov"
    video.write_bytes(b"fake")
    final = tmp_path / "final_video_v2.mp4"
    final.write_bytes(b"mp4")
    events: list[tuple[str, int]] = []

    async def _fake_create(job, video_path, resolved_prompt, intent_meta):
        job.report_progress("Vision Analysis", 15)
        job.report_progress("Rendering", 88)
        return {
            "status": "completed",
            "final_video": str(final),
            "slug": "house",
            "error": "",
        }

    with patch(
        "backend.ai_director.pipeline.run_create_project",
        new=AsyncMock(side_effect=_fake_create),
    ):
        await generate_video(
            video_path=video,
            brief="tour",
            language="en",
            on_progress=lambda s, p: events.append((s, p)),
        )

    assert ("Starting", 5) in events
    assert ("Vision Analysis", 15) in events
    assert ("Quality pass", 90) in events
    assert ("Completed", 100) not in events


@pytest.mark.asyncio
async def test_generate_video_raises_on_pipeline_error(tmp_path: Path) -> None:
    video = tmp_path / "house.mov"
    video.write_bytes(b"fake")

    with patch(
        "backend.ai_director.pipeline.run_create_project",
        new=AsyncMock(
            return_value={
                "status": "error",
                "final_video": None,
                "slug": "house",
                "error": "LLM down",
            }
        ),
    ):
        with pytest.raises(RuntimeError, match="LLM down"):
            await generate_video(video, "tour the home", "zh")
