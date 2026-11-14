"""Public AI Director pipeline facade.

Wraps the existing orchestrator create-project path so CLI / Web / Workers
can call one function without depending on Studio Job plumbing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.progress import JobCancelled, ProgressCallback
from backend.workflow.jobs import Job, StageState
from backend.workflow.orchestrator import run_create_project
from backend.workflows.user_intent import resolve_user_intent


def _normalize_language(language: str) -> str:
    """Map common labels to internal codes ``en`` / ``zh``."""
    lang = (language or "zh").strip().lower()
    if lang in ("en", "english"):
        return "en"
    if lang in ("zh", "chinese", "中文", "zh-cn", "zh_cn", "zh-hans"):
        return "zh"
    if lang not in ("en", "zh"):
        raise ValueError("language must be 'en'/'English' or 'zh'/'Chinese'")
    return lang


def _make_api_job(
    slug: str = "",
    on_progress: Optional[ProgressCallback] = None,
) -> Job:
    """In-memory job for progress tracking (same stages as Studio create)."""
    return Job(
        id="generate_video",
        slug=slug,
        kind="create_project",
        stages=[
            StageState(name="vision", label="Understanding the property"),
            StageState(name="story", label="Creating the story & narration"),
            StageState(name="editing", label="Directing the edit"),
            StageState(name="evaluation", label="Quality pass & final render"),
        ],
        on_progress=on_progress,
    )


async def generate_video(
    video_path: str | Path,
    brief: str,
    language: str = "zh",
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """Public AI Director API — run the full pipeline, return final video path.

    Args:
        video_path: Source walkthrough video.
        brief: Director instruction (what to emphasize).
        language: Narration language — ``zh`` / ``en`` (also accepts English/Chinese).
        on_progress: Optional ``(stage: str, progress: int) -> None`` callback.
            Fired at each Vision / Story / Editing / Render boundary so Worker
            or Backend can persist SaaS job progress.

    Returns:
        Absolute path to the final rendered MP4.

    Raises:
        FileNotFoundError: Source video missing.
        RuntimeError: Pipeline failed or final file not produced.
        ValueError: Unsupported language.
    """
    path = Path(video_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    lang = _normalize_language(language)
    resolved = resolve_user_intent(brief, interactive=False, language=lang)
    intent_meta: dict[str, Any] = {
        "intent_source": resolved.source,
        "intent_was_vague": resolved.was_vague,
        "intent_original": resolved.original_prompt,
        "narration_language": lang,
    }

    if on_progress:
        on_progress("Starting", 5)

    job = _make_api_job(on_progress=on_progress)
    result = await run_create_project(
        job=job,
        video_path=path,
        resolved_prompt=resolved.prompt,
        intent_meta=intent_meta,
    )

    if result.get("status") == "cancelled":
        raise JobCancelled(result.get("error") or "Cancelled by user")
    if result.get("status") != "completed" or not result.get("final_video"):
        raise RuntimeError(result.get("error") or "AI Director pipeline failed")

    final = Path(result["final_video"])
    if not final.exists():
        raise RuntimeError(f"Pipeline reported final video but file missing: {final}")

    # Do not report 100/Completed here — SaaS Worker still uploads final video
    # and studio workspace; only complete_job should mark the job done.
    if on_progress:
        on_progress("Quality pass", 90)

    return final.resolve()
