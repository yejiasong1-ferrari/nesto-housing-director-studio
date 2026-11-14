"""Audio Balance Evaluator — narration must dominate fixed BGM.

V1: no music-style critique. Only check configured BGM level vs narration.
Deterministic rules; no LLM.
"""

from __future__ import annotations

from typing import Any

from backend.agents.evaluation.evaluators._helpers import clamp_score
from backend.schemas.audio_schema import AudioConfig, DEFAULT_BGM_VOLUME_DB
from backend.schemas.evaluation_schema import EvaluationIssue

# BGM louder than this (less negative) risks drowning narration
BGM_TOO_LOUD_DB = -14.0
# Soft warning band. -18 dB is the established final-mix target; do not
# flag that same accepted level on the next project.
BGM_WARN_DB = -18.0


class AudioBalanceEvaluator:
    """Check voice >> BGM using workflow audio_config + render metadata."""

    weight = 0.0  # folded into technical score by EvaluationAgent

    def evaluate(
        self,
        audio_config: AudioConfig | dict[str, Any] | None,
        render: dict[str, Any],
    ) -> tuple[float, list[EvaluationIssue]]:
        issues: list[EvaluationIssue] = []
        penalties = 0.0

        cfg = self._normalize(audio_config)
        bgm = cfg.background_music

        if not bgm.enabled:
            return 100.0, issues

        # Prefer actual mix metadata from render; fall back to config
        volume_db = render.get("bgm_volume_db")
        if volume_db is None:
            volume_db = bgm.volume_db
        try:
            volume_db = float(volume_db)
        except (TypeError, ValueError):
            volume_db = DEFAULT_BGM_VOLUME_DB

        bgm_mixed = bool(render.get("bgm_mixed", False))
        bgm_path = str(render.get("bgm_path") or bgm.path or "")

        if render and render.get("status") == "success" and not bgm_mixed:
            issues.append(EvaluationIssue(
                type="bgm_missing",
                segment_id="",
                severity="low",
                description="BGM enabled in audio_config but not mixed into final video",
                evidence={"bgm_path": bgm_path, "enabled": True},
                suggested_target="rendering",
            ))
            penalties += 8

        if volume_db > BGM_TOO_LOUD_DB:
            # Suggest stepping down toward safe default
            suggested = min(volume_db - 5.0, DEFAULT_BGM_VOLUME_DB)
            issues.append(EvaluationIssue(
                type="bgm_overwhelms_narration",
                segment_id="",
                severity="high",
                description=(
                    f"Background music overwhelms narration "
                    f"(bgm={volume_db:.1f} dB; voice should stay ~0 dB)"
                ),
                evidence={
                    "bgm_volume_db": volume_db,
                    "voice_level_db": 0.0,
                    "suggested_bgm_volume_db": suggested,
                },
                suggested_target="rendering",
            ))
            penalties += 25
        elif volume_db > BGM_WARN_DB:
            suggested = min(volume_db - 3.0, DEFAULT_BGM_VOLUME_DB)
            issues.append(EvaluationIssue(
                type="bgm_overwhelms_narration",
                segment_id="",
                severity="medium",
                description=(
                    f"BGM may compete with narration "
                    f"(bgm={volume_db:.1f} dB; prefer ≤ {BGM_WARN_DB:.0f} dB)"
                ),
                evidence={
                    "bgm_volume_db": volume_db,
                    "voice_level_db": 0.0,
                    "suggested_bgm_volume_db": suggested,
                },
                suggested_target="rendering",
            ))
            penalties += 10

        return clamp_score(100.0 - penalties), issues

    def _normalize(
        self, audio_config: AudioConfig | dict[str, Any] | None
    ) -> AudioConfig:
        if audio_config is None:
            return AudioConfig()
        if isinstance(audio_config, AudioConfig):
            return audio_config
        return AudioConfig.model_validate(audio_config)
