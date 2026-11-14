"""Unit tests for fixed-BGM AudioMixer / BGMHandler (no full video render)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.agents.rendering.audio.bgm_handler import BGMHandler
from backend.agents.rendering.audio.mixer import AudioMixer, db_to_linear
from backend.schemas.audio_schema import AudioConfig, BackgroundMusicConfig, resolve_bgm_path


def test_default_bgm_exists() -> None:
    path = resolve_bgm_path()
    assert path.exists(), f"Missing default BGM at {path}"


def test_db_to_linear() -> None:
    assert abs(db_to_linear(0) - 1.0) < 1e-6
    assert abs(db_to_linear(-20) - 0.1) < 1e-6
    assert db_to_linear(-25) < 0.06


def test_bgm_handler_trim_and_loop(tmp_path: Path) -> None:
    from moviepy import AudioClip

    # 1s tone as fake BGM
    tone = AudioClip(lambda t: np.sin(2 * np.pi * 440 * t), duration=1.0, fps=22050)
    bgm_path = tmp_path / "tone.mp3"
    tone.write_audiofile(str(bgm_path), fps=22050, logger=None)
    tone.close()

    handler = BGMHandler()
    loaded = handler.load(bgm_path)
    trimmed = handler.fit(loaded, 0.5, allow_loop=True)
    assert abs(trimmed.duration - 0.5) < 0.08
    trimmed.close()
    loaded.close()

    loaded2 = handler.load(bgm_path)
    looped = handler.fit(loaded2, 2.5, allow_loop=True)
    assert abs(looped.duration - 2.5) < 0.08
    looped.close()
    loaded2.close()


def test_mixer_disabled_returns_narration_only() -> None:
    from moviepy import AudioClip

    narr = AudioClip(lambda t: 0.2, duration=1.0, fps=22050)
    mixer = AudioMixer()
    cfg = AudioConfig(background_music=BackgroundMusicConfig(enabled=False))
    out, meta = mixer.mix(narr, target_duration=1.0, audio_config=cfg)
    assert meta["bgm_mixed"] is False
    assert abs(out.duration - 1.0) < 0.05
    out.close()
    narr.close()


def test_mixer_mixes_default_bgm() -> None:
    from moviepy import AudioClip

    narr = AudioClip(lambda t: 0.3, duration=2.0, fps=22050)
    mixer = AudioMixer()
    out, meta = mixer.mix(narr, target_duration=2.0, audio_config=AudioConfig())
    assert meta["bgm_mixed"] is True
    assert meta["bgm_volume_db"] == -18.0
    assert Path(meta["bgm_path"]).exists()
    assert abs(out.duration - 2.0) < 0.1
    out.close()
    narr.close()


def test_audio_balance_flags_loud_bgm() -> None:
    from backend.agents.evaluation.evaluators.audio_balance import AudioBalanceEvaluator

    ev = AudioBalanceEvaluator()
    cfg = AudioConfig(
        background_music=BackgroundMusicConfig(enabled=True, volume_db=-10)
    )
    score, issues = ev.evaluate(cfg, {"status": "success", "bgm_mixed": True, "bgm_volume_db": -10})
    assert any(i.type == "bgm_overwhelms_narration" for i in issues)
    assert score < 100


def test_audio_balance_accepts_final_mix_default() -> None:
    from backend.agents.evaluation.evaluators.audio_balance import AudioBalanceEvaluator

    cfg = AudioConfig()
    score, issues = AudioBalanceEvaluator().evaluate(
        cfg,
        {
            "status": "success",
            "bgm_mixed": True,
            "bgm_volume_db": cfg.background_music.volume_db,
        },
    )
    assert score == 100
    assert not issues
