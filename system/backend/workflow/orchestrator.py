"""Revision Orchestrator — sequences Agents/Services for one human edit.

Runs in-process as an asyncio background task per Job. Only touches the
stages the dependency graph says are invalidated; everything else on disk
is left untouched (Vision/Planner are never re-run for a Studio edit).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# system/backend/workflow → parents[2] = system/, parents[3] = repo root
_SYSTEM_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SYSTEM_ROOT.parent
for _p in (_SYSTEM_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
REPO_ROOT = _REPO_ROOT

from backend.workflow.jobs import Job, job_store  # noqa: E402
from backend.workflow import revision_engine  # noqa: E402
from backend.workflow.dependency_graph import plan_revision  # noqa: E402
from backend.progress import JobCancelled  # noqa: E402

logger = logging.getLogger(__name__)

from backend.services.llm.config import (  # noqa: E402
    openai_api_key,
    openai_base_url,
    openai_model,
)

BASE_URL = openai_base_url()
API_KEY = openai_api_key()
LLM_MODEL = openai_model()
VOLCENGINE_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
VOLCENGINE_RESOURCE_ID = "seed-tts-1.0"


def _ensure_not_cancelled(job: Job) -> None:
    if job.cancel_requested:
        raise JobCancelled()

# Fallback canvas size passed into RenderingAgent; RenderService overrides to
# source orientation at render time (landscape 1920×1080 / portrait 1080×1920).
FINAL_SIZE = (1920, 1080)


def llm_reachable(timeout: float = 1.5) -> bool:
    parsed = urlparse(BASE_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _make_llm():
    from backend.services.llm.openai_provider import OpenAIProvider
    return OpenAIProvider(api_key=API_KEY, base_url=BASE_URL, default_model=LLM_MODEL)


def _load(p: Path) -> dict:
    import json
    return json.loads(p.read_text()) if p.exists() else {}


# ---------------------------------------------------------------------------
# Script edit → re-synthesize one segment's voice (no video render)
# ---------------------------------------------------------------------------

async def run_script_update(job: Job, ws, segment_id: str, new_text: str) -> None:
    plan = plan_revision("script_update", segment_id)
    try:
        job.status = "running"
        job.set_stage("apply", "running", "Saving your edit")
        revision_engine.patch_script_text(ws, segment_id, new_text)
        job.set_stage("apply", "done")

        job.set_stage("voice", "running", "Re-recording narration")
        api_key = os.environ.get("VOLCENGINE_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "VOLCENGINE_API_KEY is not set on the backend — cannot re-synthesize voice."
            )
        from backend.schemas.voice_schema import VoiceDelivery, VoiceProfile, VoiceSegmentPlan, VoicePlan
        from backend.services.voice_executor import VoiceExecutionService

        voice_exec = _load(ws.voice_execution_path)
        voice_plan_raw = _load(ws.voice_plan_path).get("voice_plan", {})
        profile_raw = voice_plan_raw.get("profile") or {}
        profile = VoiceProfile.model_validate(profile_raw) if profile_raw else VoiceProfile()

        seg_plan = VoiceSegmentPlan(
            id=f"voice_{segment_id}",
            script_id=segment_id,
            text=new_text,
            tts_text=new_text,
            delivery=VoiceDelivery(),
        )
        one_plan = VoicePlan(profile=profile, segments=[seg_plan])

        executor = VoiceExecutionService(
            api_key=api_key,
            endpoint=VOLCENGINE_ENDPOINT,
            resource_id=VOLCENGINE_RESOURCE_ID,
            default_speaker=profile.voice_id,
        )
        execution = await executor.synthesize_plan(one_plan, ws.audio_dir, project_id=ws.slug)
        if not execution.segments:
            raise RuntimeError("TTS returned no audio for the edited segment")
        synthesized = execution.segments[0]

        # Merge into voice_execution.json so future runs see the new duration
        by_id = {s.get("script_id"): s for s in (voice_exec.get("segments") or [])}
        by_id[segment_id] = synthesized.model_dump(mode="json")
        voice_exec["segments"] = list(by_id.values())
        import json as _json
        ws.voice_execution_path.write_text(_json.dumps(voice_exec, indent=2, default=str), encoding="utf-8")

        revision_engine.patch_audio_paths(
            ws, segment_id, synthesized.audio_path, synthesized.duration
        )
        try:
            from backend.workspace_paths import rewrite_workspace_media_paths

            rewrite_workspace_media_paths(ws.root)
        except Exception as exc:  # noqa: BLE001
            logger.warning("audio path rewrite after script_update: %s", exc)
        job.set_stage("voice", "done", f"New duration {synthesized.duration:.1f}s")

        job.set_stage("subtitle", "done", "Subtitle will follow narration on export")

        job.result = {
            "invalidated": list(plan.invalidated),
            "audio_duration": synthesized.duration,
            "pending_export": True,
        }
        job.status = "done"
    except Exception as exc:
        logger.exception("script_update job failed")
        job.status = "error"
        job.error = str(exc)
        for s in job.stages:
            if s.status == "running":
                s.status = "error"
    finally:
        job.touch()


# ---------------------------------------------------------------------------
# Audio nudge → persist offset only (no video render until export)
# ---------------------------------------------------------------------------

async def run_audio_offset(job: Job, ws, segment_id: str, offset_seconds: float) -> None:
    plan = plan_revision("audio_offset", segment_id)
    try:
        job.status = "running"
        job.set_stage("apply", "running", "Adjusting narration timing")
        applied = revision_engine.patch_audio_offset(ws, segment_id, offset_seconds)
        job.set_stage("apply", "done", f"Offset {applied:.2f}s")

        job.result = {
            "invalidated": list(plan.invalidated),
            "applied_offset": applied,
            "pending_export": True,
        }
        job.status = "done"
    except Exception as exc:
        logger.exception("audio_offset job failed")
        job.status = "error"
        job.error = str(exc)
        for s in job.stages:
            if s.status == "running":
                s.status = "error"
    finally:
        job.touch()


# ---------------------------------------------------------------------------
# Export → final render from current (possibly edited) state
# ---------------------------------------------------------------------------

async def run_export(job: Job, ws) -> None:
    try:
        job.status = "running"
        _ensure_not_cancelled(job)
        job.set_stage("prepare", "running", "Collecting script, voice, and timing edits")
        # Touch inputs so failures surface before the long render.
        if not ws.editing_plan_path.exists():
            raise RuntimeError("Editing plan missing — cannot export")
        try:
            from backend.workspace_paths import (
                materialize_workspace_audio_paths,
                rewrite_workspace_media_paths,
            )

            rewrite_workspace_media_paths(ws.root)
            materialize_workspace_audio_paths(ws.root)
        except Exception as exc:  # noqa: BLE001
            logger.warning("audio path rewrite before export: %s", exc)
        job.set_stage("prepare", "done")

        _ensure_not_cancelled(job)
        job.set_stage("render", "running", "Rendering final video")
        result = await _render(ws, FINAL_SIZE, ws.final_video_v2_path)
        _ensure_not_cancelled(job)
        if result.get("status") != "success":
            job.set_stage("render", "error", result.get("error", "Render failed"))
            job.result = {"render": result}
            job.status = "error"
            job.error = result.get("error", "Render failed")
            return
        job.set_stage("render", "done")

        _ensure_not_cancelled(job)
        job.set_stage("finalize", "running", "Writing final video")
        job.set_stage("finalize", "done", str(ws.final_video_v2_path.name))
        job.result = {"render": result}
        job.status = "done"
    except JobCancelled:
        job.mark_cancelled()
    except Exception as exc:
        logger.exception("export job failed")
        job.status = "error"
        job.error = str(exc)
        for s in job.stages:
            if s.status == "running":
                s.status = "error"
    finally:
        job.touch()


async def _render(ws, size: tuple[int, int], output_path: Path) -> dict[str, Any]:
    from backend.agents.rendering.agent import RenderingAgent
    from backend.configs import agent_section
    from backend.state.project_state import ProjectState

    editing = _load(ws.editing_plan_path)
    timeline = _load(ws.timeline_output_path)
    script = _load(ws.timeline_script_path) or _load(ws.script_output_path)
    voice = _load(ws.voice_execution_path)

    state = ProjectState(
        project_id=ws.slug,
        editing=editing,
        timeline=timeline,
        script=script,
        voice=voice,
    )
    agent = RenderingAgent(
        config=agent_section("rendering"),
        source_video_path=str(ws.video_path),
        output_path=str(output_path),
        output_width=size[0],
        output_height=size[1],
        fps=30,
    )
    state = await agent.run(state)
    return state.render


# ---------------------------------------------------------------------------
# New project — full pipeline (Vision → ... → Rendering → Evaluation)
# ---------------------------------------------------------------------------

def _resolve_final_video(ws) -> Path:
    """Prefer evaluation final (v2); fall back to draft render."""
    if ws.final_video_v2_path.exists():
        return ws.final_video_v2_path
    return ws.final_video_path


async def run_create_project(
    job: Job,
    video_path: Path,
    resolved_prompt: str,
    intent_meta: dict,
) -> dict[str, Any]:
    """Run the full create-project pipeline.

    Mutates ``job`` for Studio progress polling. Also returns a result dict
    so Python callers (``generate_video``) can read the final video path:

        {"status": "completed"|"cancelled"|"error", "final_video": str|None, ...}
    """
    result: dict[str, Any] = {
        "status": "error",
        "final_video": None,
        "slug": job.slug or "",
        "error": "",
    }
    try:
        job.status = "running"

        if not llm_reachable():
            raise RuntimeError(
                f"LLM server not reachable at {BASE_URL}. Start it before creating a project."
            )
        volc_key = os.environ.get("VOLCENGINE_API_KEY", "")
        if not volc_key:
            raise RuntimeError("VOLCENGINE_API_KEY is not set on the backend.")

        # CLI runners live at repo root (Mac Worker / local Studio).
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        try:
            import run_vision_full  # noqa: F401
            import run_full_pipeline  # noqa: F401
            import run_editing_rendering  # noqa: F401
            import run_evaluation  # noqa: F401
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Pipeline runners not available on this server. "
                "Production creates should use the Worker queue "
                "(POST /api/projects → upload → /api/jobs). "
                f"Missing module: {exc.name}"
            ) from exc
        from backend.tools.property_workspace import resolve_workspace

        ws = resolve_workspace(video_path)
        job.slug = ws.slug
        result["slug"] = ws.slug

        _ensure_not_cancelled(job)
        job.set_stage("vision", "running", "Watching the walkthrough")
        stage_started = time.monotonic()
        await run_vision_full.run_full_pipeline(video_path)
        logger.info(
            "Pipeline timing stage=vision seconds=%.2f",
            time.monotonic() - stage_started,
        )
        job.set_stage("vision", "done")

        _ensure_not_cancelled(job)
        job.set_stage("story", "running", "Planning the story and writing narration")
        stage_started = time.monotonic()
        await run_full_pipeline.run_pipeline(
            resolved_prompt, video_path, skip_tts=False, max_tts_segments=None,
            intent_meta=intent_meta,
        )
        logger.info(
            "Pipeline timing stage=story_voice seconds=%.2f",
            time.monotonic() - stage_started,
        )
        job.set_stage("story", "done")

        _ensure_not_cancelled(job)
        job.set_stage("editing", "running", "Directing the edit")
        stage_started = time.monotonic()
        await run_editing_rendering.run(ws, video_path)
        logger.info(
            "Pipeline timing stage=draft_render seconds=%.2f",
            time.monotonic() - stage_started,
        )
        job.set_stage("editing", "done")

        _ensure_not_cancelled(job)
        job.set_stage("evaluation", "running", "Quality pass & final render")
        stage_started = time.monotonic()
        await run_evaluation.main(video_path, on_progress=job.report_progress)
        logger.info(
            "Pipeline timing stage=evaluation_final seconds=%.2f",
            time.monotonic() - stage_started,
        )
        job.set_stage("evaluation", "done")

        _ensure_not_cancelled(job)
        final_path = _resolve_final_video(ws)
        if not final_path.exists():
            raise RuntimeError(f"Pipeline finished but final video missing: {final_path}")

        job.result = {"slug": ws.slug, "final_video": str(final_path)}
        job.status = "done"
        result = {
            "status": "completed",
            "final_video": str(final_path),
            "slug": ws.slug,
            "error": "",
        }
    except JobCancelled:
        job.mark_cancelled()
        result = {
            "status": "cancelled",
            "final_video": None,
            "slug": job.slug,
            "error": job.error or "Cancelled by user",
        }
    except Exception as exc:
        logger.exception("create_project job failed")
        job.status = "error"
        job.error = str(exc)
        for s in job.stages:
            if s.status == "running":
                s.status = "error"
        result = {
            "status": "error",
            "final_video": None,
            "slug": job.slug,
            "error": str(exc),
        }
    finally:
        job.touch()
    return result
