"""Regression tests for quality-preserving BGM-only finalization."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from backend.agents.rendering.render_service import RenderService
from backend.schemas.audio_schema import AudioConfig, BackgroundMusicConfig
from backend.schemas.evaluation_schema import FixAction, PriorityFix

from run_evaluation import _is_bgm_only_feedback


def _run(*args: str) -> None:
    subprocess.run(list(args), check=True, capture_output=True, text=True)


def _stream_md5(path: Path, stream: str) -> str:
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path),
            "-map", stream, "-c", "copy", "-f", "md5", "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_bgm_only_classifier_is_strict() -> None:
    from run_evaluation import _is_bgm_only_applied, _should_reuse_draft

    bgm = PriorityFix(
        target_agent="rendering_agent",
        action=FixAction(type="adjust_bgm_volume", value=-23),
    )
    subtitle = PriorityFix(
        target_agent="editing_agent",
        action=FixAction(type="shorten_subtitle"),
    )
    assert _is_bgm_only_feedback([bgm], []) is True
    assert _is_bgm_only_feedback([bgm], ["tl_001"]) is False
    assert _is_bgm_only_feedback([bgm, subtitle], []) is False
    assert _is_bgm_only_feedback([], []) is False
    assert _should_reuse_draft([], []) is True
    assert _should_reuse_draft([{"action": "extend_window"}], []) is False
    assert _is_bgm_only_applied([{"action": "adjust_bgm_volume"}], []) is True
    assert _is_bgm_only_applied([], []) is False


def test_audio_only_remix_copies_video_and_faststarts(tmp_path: Path) -> None:
    source = tmp_path / "draft.mp4"
    narration = tmp_path / "voice.wav"
    output = tmp_path / "final.mp4"
    timing = tmp_path / "studio_timing.json"

    _run(
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(source),
    )
    _run(
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
        str(narration),
    )
    timing.write_text(
        json.dumps({
            "duration": 1.0,
            "segments": [{
                "id": "tl_001",
                "video_start": 0.0,
                "video_duration": 1.0,
                "narration_at": 0.0,
                "audio_duration": 0.6,
            }],
        }),
        encoding="utf-8",
    )
    plan = {
        "project_id": "test",
        "segments": [{
            "segment_id": "tl_001",
            "audio_path": str(narration),
            "audio_duration": 0.6,
            "video_start": 0.0,
            "video_end": 1.0,
            "video_duration": 1.0,
            "editing_window": 1.0,
            "subtitle": {"enabled": False},
        }],
    }
    cfg = AudioConfig(
        background_music=BackgroundMusicConfig(enabled=False, volume_db=-23),
    )

    result = RenderService().remix_audio_only(
        source,
        plan,
        output,
        audio_config=cfg,
        studio_timing_path=timing,
        prior_render={
            "project_id": "test",
            "status": "success",
            "duration": 1.0,
            "width": 320,
            "height": 180,
        },
    )

    assert result.status == "success"
    assert output.exists()
    assert _stream_md5(source, "0:v:0") == _stream_md5(output, "0:v:0")
    data = output.read_bytes()
    assert 0 < data.find(b"moov") < data.find(b"mdat")
