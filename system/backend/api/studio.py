"""AI Director Studio API — Human-in-the-loop revision endpoints.

Reads/writes the same on-disk artifacts as the CLI runners
(storage/properties/<slug>/...). A human edit here never re-runs the whole
pipeline — the Revision Engine + Orchestrator recompute only the
invalidated stages (see backend/workflow/).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.api.invite import require_beta_session, require_write_session
from backend.database import db as saas_db
from backend.invite_db import BetaSession
from backend.tools.property_workspace import (
    PROJECT_ROOT,
    STORAGE_ROOT,
    resolve_workspace,
    resolve_workspace_by_slug,
    slug_from_name,
)
from backend.workflow import orchestrator
from backend.workflow.jobs import job_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio")

TAG_STUDIO_PROJECTS = "⑤ Studio · 项目"
TAG_STUDIO_REVISE = "⑥ Studio · 修改 Script / Audio"
TAG_STUDIO_JOBS = "⑦ Studio · 导出与任务"

STAGE_ORDER = ["vision", "planner", "script", "voice", "timeline", "editing", "rendering"]


async def _ensure_workspace_root(slug: str) -> Path:
    """Return local workspace root, hydrating from R2 when needed."""
    root = STORAGE_ROOT / slug
    if (root / "property.json").exists():
        return root
    try:
        from backend.workspace_hydrate import ensure_workspace_local

        return await asyncio.to_thread(ensure_workspace_local, slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("workspace hydrate failed for %s: %s", slug, exc)
        raise HTTPException(status_code=404, detail="Project not found") from exc


def _load(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


def _to_media_url(abs_path: str) -> str | None:
    if not abs_path:
        return None
    try:
        rel = Path(abs_path).resolve().relative_to(STORAGE_ROOT.resolve())
    except ValueError:
        return None
    return f"/media/{rel.as_posix()}"


def _r2_presigned_final_for_slug(slug: str) -> str | None:
    """Prefer Cloudflare R2 direct play URL over Railway /media proxy."""
    try:
        project = saas_db.find_project_by_workspace_slug(slug)
    except Exception:  # noqa: BLE001
        return None
    if not project:
        return None
    uri = project.final_video or ""
    if not uri or not str(uri).startswith("r2://"):
        return None
    try:
        from backend import r2 as r2_mod

        _bucket, key = r2_mod.parse_r2_uri(str(uri))
        return r2_mod.generate_download_url(key, expires_in=3600)
    except Exception as exc:  # noqa: BLE001
        logger.warning("R2 presign for slug %s failed: %s", slug, exc)
        return None


def _stage_flags(ws) -> dict[str, bool]:
    return {
        "vision": ws.vkb_path.exists(),
        "planner": ws.planner_output_path.exists(),
        "script": ws.script_output_path.exists(),
        "voice": ws.voice_execution_path.exists(),
        "timeline": ws.timeline_output_path.exists(),
        "editing": ws.editing_plan_path.exists(),
        "rendering": (
            ws.final_video_v2_path.exists()
            or ws.final_video_path.exists()
            or (ws.output_dir / "preview.mp4").exists()
        ),
    }


def _project_summary(slug: str) -> dict[str, Any] | None:
    root = STORAGE_ROOT / slug
    meta_path = root / "property.json"
    if not meta_path.exists():
        return None
    meta = _load(meta_path)
    ws = resolve_workspace_by_slug(slug, meta.get("video_path"))
    flags = _stage_flags(ws)

    timeline = _load(ws.timeline_output_path)
    render = _load(ws.output_dir / "render_result_v2.json") or _load(ws.render_result_path)
    evaluation = _load(ws.evaluation_result_path)
    vkb = _load(ws.vkb_path)

    final_url = _to_media_url(str(ws.final_video_v2_path)) if ws.final_video_v2_path.exists() else (
        _to_media_url(str(ws.final_video_path)) if ws.final_video_path.exists() else None
    )

    return {
        "slug": slug,
        "video_name": meta.get("video_name", slug),
        "updated_at": meta.get("updated_at", ""),
        "director_brief": meta.get("user_prompt", ""),
        "stages": flags,
        "all_complete": all(flags.values()),
        "segment_count": len(timeline.get("segments") or []),
        "room_count": len(vkb.get("segments") or []),
        "duration": render.get("duration") or timeline.get("total_duration") or 0,
        "overall_score": evaluation.get("overall_score"),
        "final_video_url": final_url,
    }


def _session_owns_slug(session: BetaSession, slug: str) -> bool:
    """True if SaaS project for slug belongs to this beta account (or no SaaS row)."""
    project = saas_db.find_project_by_workspace_slug(slug)
    if not project or not project.beta_account_id:
        # Local-only workspaces: allow read for any authenticated beta (legacy Studio)
        # but prefer ownership when linked.
        return True
    return project.beta_account_id == session.beta_account_id


@router.get(
    "/projects",
    tags=[TAG_STUDIO_PROJECTS],
    summary="列出 Studio 项目",
    description="返回本地 `storage/properties/` 下已生成的项目摘要（slug、阶段完成情况、成片链接等）。",
)
async def list_projects(
    session: BetaSession = Depends(require_beta_session),
) -> list[dict[str, Any]]:
    if not STORAGE_ROOT.exists():
        return []
    out = []
    for d in sorted(STORAGE_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        if not _session_owns_slug(session, d.name):
            continue
        summary = _project_summary(d.name)
        if summary:
            out.append(summary)
    return out


def _room_type(vkb_seg: dict) -> str:
    k = vkb_seg.get("knowledge") or {}
    return k.get("room_type") or k.get("room") or ""


def _space_labels_from_segment(vkb_seg: dict) -> list[dict[str, Any]]:
    """Flatten VKB segment spaces for Detected spaces UI."""
    k = vkb_seg.get("knowledge") or {}
    conf = float(vkb_seg.get("confidence") or k.get("confidence") or 0)
    spaces = k.get("spaces") or []
    out: list[dict[str, Any]] = []
    if isinstance(spaces, list) and spaces:
        for sp in spaces:
            if not isinstance(sp, dict):
                continue
            label = (
                sp.get("display_name")
                or sp.get("narration_name")
                or sp.get("type")
                or sp.get("room")
                or sp.get("room_type")
                or ""
            ).strip()
            if not label:
                continue
            out.append({
                "room": label,
                "confidence": float(sp.get("confidence") or conf or 0),
                "instance": sp.get("instance"),
                "instance_id": sp.get("instance_id"),
                "room_role": sp.get("room_role") or "",
                "features": sp.get("features") or [],
            })
        return out

    room = _room_type(vkb_seg)
    if room:
        out.append({"room": room, "confidence": conf})
    return out


def _thinking_summary(ws) -> dict[str, Any]:
    vkb = _load(ws.vkb_path)
    timeline = _load(ws.timeline_output_path)

    rooms: list[dict[str, Any]] = []
    seen_rooms: set[str] = set()
    highlights: list[str] = []
    for seg in vkb.get("segments") or []:
        k = seg.get("knowledge") or {}
        for item in _space_labels_from_segment(seg):
            key = str(item.get("room", "")).lower()
            if key and key not in seen_rooms:
                seen_rooms.add(key)
                rooms.append(item)
        for sp in (k.get("selling_points") or [])[:2]:
            text = sp if isinstance(sp, str) else (sp.get("description") or sp.get("text") or "")
            if text and text not in highlights:
                highlights.append(text)

    opening: list[str] = []
    middle: list[str] = []
    ending: list[str] = []
    for seg in timeline.get("segments") or []:
        room = seg.get("room_type", "")
        arc = seg.get("arc_stage", "")
        role = seg.get("role", "")
        if arc in ("hook", "open") or role == "TRANSITION" and not middle:
            if room and room not in opening:
                opening.append(room)
        elif arc in ("close", "ending") or (role == "TRANSITION" and middle):
            if room and room not in ending:
                ending.append(room)
        else:
            if room and room not in middle:
                middle.append(room)

    return {
        "rooms": rooms,
        "highlights": highlights[:6],
        "story": {
            "opening": opening,
            "middle": middle,
            "ending": ending,
        },
        "narration_count": len(timeline.get("segments") or []),
    }


def _segment_output_window(ed: dict[str, Any], video_duration: float, audio_dur: float = 0.0) -> float:
    """Match RenderingAgent target window so Studio timing ≈ final video."""
    from backend.configs import preserve_full_span_enabled

    window = float(ed.get("editing_window") or 0) or video_duration
    if audio_dur > 0:
        window = max(window, audio_dur + 0.40)
    # v2.2 continuous walkthrough: never schedule shorter than extracted span
    if preserve_full_span_enabled():
        window = max(window, video_duration)
    return max(0.1, window)


def _transition_overlap(ed: dict[str, Any], window: float) -> float:
    """Same caps as TransitionProcessor / RenderService audio cursor."""
    from backend.configs import continuous_walkthrough_enabled

    if continuous_walkthrough_enabled():
        return 0.0
    if window < 1.5:
        return 0.0
    transition = ed.get("transition") or {}
    t_type = ed.get("transition_type") or transition.get("type") or "cut"
    t_dur = float(ed.get("transition_duration") or transition.get("duration") or 0)
    if t_type not in ("dissolve", "soft_pan", "camera_pan") or t_dur <= 0:
        return 0.0
    return min(float(t_dur), 0.35)


def _load_studio_timing(ws) -> dict[str, dict[str, Any]]:
    """Prefer the sidecar written by the last successful render."""
    data = _load(ws.output_dir / "studio_timing.json")
    if data.get("segments"):
        return {s.get("id"): s for s in data["segments"] if s.get("id")}
    return {}


def _probe_audio_duration(path: str, fallback: float = 0.0) -> float:
    try:
        from backend.agents.rendering.processors.audio_processor import probe_audio_duration
        return probe_audio_duration(path, fallback)
    except Exception:
        return float(fallback or 0.0)


def _merge_timeline_segments(ws) -> list[dict[str, Any]]:
    timeline = {s.get("id"): s for s in (_load(ws.timeline_output_path).get("segments") or [])}
    editing = _load(ws.editing_plan_path).get("segments") or []
    timing_by_id = _load_studio_timing(ws)

    out: list[dict[str, Any]] = []
    for ed in editing:
        sid = ed.get("segment_id", "")
        tl = timeline.get(sid, {})
        src = tl.get("source") or {}
        v_start = float(ed.get("video_start", src.get("video_start", 0)) or 0)
        v_end = float(ed.get("video_end", src.get("video_end", 0)) or 0)
        video_duration = round(max(0.1, v_end - v_start), 2)
        timed = timing_by_id.get(sid) or {}

        audio_path = ed.get("audio_path") or ""
        meta_aud = float(ed.get("audio_duration") or 0)
        probed = _probe_audio_duration(str(audio_path), meta_aud) or meta_aud
        timed_aud = float(timed.get("audio_duration") or 0)
        # Sidecar may still carry the old half-length metadata — prefer the
        # real file duration whenever it is substantially longer.
        if timed_aud > 0.1 and probed <= timed_aud * 1.5 + 0.3:
            audio_dur = timed_aud
        else:
            audio_dur = probed or timed_aud or meta_aud

        audio_offset = float(ed.get("audio_offset", 0.0) or 0.0)
        output_duration = round(
            _segment_output_window(ed, video_duration, audio_dur),
            3,
        )
        # Layout must cover offset + full narration.
        output_duration = max(output_duration, audio_offset + audio_dur + 0.05)

        vs = ed.get("visual_strategy") or {}
        ops = vs.get("operations") or []
        if not ops and ed.get("visual_strategies"):
            legacy = ed["visual_strategies"][0]
            primary = {"type": legacy.get("type", "clean_cut"), "target": "", "strength": 0.5}
        elif ops:
            primary = {
                "type": ops[0].get("type", "clean_cut"),
                "target": ops[0].get("target", ""),
                "strength": ops[0].get("strength", 0.5),
            }
        else:
            primary = {"type": "clean_cut", "target": "", "strength": 0.5}

        dd = ed.get("director_decision") or {}
        highlight = [f.get("element", "") for f in (dd.get("focus_order") or [])][:3]

        out.append({
            "id": sid,
            "role": ed.get("role") or tl.get("role", "SUPPORT"),
            "room_type": ed.get("room_type") or tl.get("room_type", ""),
            "video_start": v_start,
            "video_end": v_end,
            "duration": video_duration,
            "editing_window": ed.get("editing_window", 0),
            "output_duration": output_duration,
            "narration_text": ed.get("narration_text", ""),
            "audio_url": _to_media_url(audio_path),
            "audio_duration": round(audio_dur, 3),
            "audio_offset": audio_offset,
            "subtitle_enabled": bool((ed.get("subtitle") or {}).get("enabled", True)),
            "visual_strategy": primary,
            "highlight": highlight,
            "pacing_style": (ed.get("pacing") or {}).get("style", "normal"),
            "media_start": timed.get("video_start"),
            "media_duration": timed.get("video_duration") or output_duration,
            "_overlap": _transition_overlap(ed, float(ed.get("editing_window") or output_duration)),
            "_audio_path": audio_path,
        })

    # Sequential non-overlapping layout + narration_at that mirrors the mixer
    # cursor_guard (previous line must finish before the next can start).
    layout_cursor = 0.0
    video_cursor = 0.0
    narr_guard = 0.0
    for i, seg in enumerate(out):
        timed = timing_by_id.get(seg["id"]) or {}
        layout_dur = float(seg["output_duration"])
        audio_offset = float(seg.get("audio_offset") or 0)
        audio_dur = float(seg.get("audio_duration") or 0)

        if timed and timed.get("video_start") is not None:
            seg["media_start"] = float(timed.get("video_start") or video_cursor)
            seg["media_duration"] = float(timed.get("video_duration") or layout_dur)
            overlap = float(seg.pop("_overlap", 0) or 0)
            video_cursor = seg["media_start"] + max(0.1, float(seg["media_duration"]) - overlap)
        else:
            seg["media_start"] = round(video_cursor, 3)
            seg["media_duration"] = layout_dur
            overlap = float(seg.pop("_overlap", 0) or 0)
            if i < len(out) - 1:
                video_cursor += max(0.1, float(seg["media_duration"]) - overlap)
            else:
                video_cursor += float(seg["media_duration"])

        # Reconstruct the mixer's no-overlap cursor using REAL file durations so
        # Bedroom→Closet playhead tracking matches what you actually hear.
        intended = float(seg["media_start"]) + audio_offset
        seg["narration_at"] = round(max(intended, narr_guard), 3)
        narr_guard = float(seg["narration_at"]) + audio_dur + 0.05
        seg.pop("_audio_path", None)

    # Re-chain layout starts sequentially with expanded durations so boxes
    # never overlap and each audio clip fits inside its scene.
    layout_cursor = 0.0
    for seg in out:
        layout_dur = max(
            float(seg["output_duration"]),
            float(seg.get("audio_offset") or 0) + float(seg.get("audio_duration") or 0) + 0.05,
        )
        seg["output_duration"] = round(layout_dur, 3)
        seg["output_start"] = round(layout_cursor, 3)
        layout_cursor += layout_dur

    return out


@router.get(
    "/projects/{slug}",
    tags=[TAG_STUDIO_PROJECTS],
    summary="获取项目详情（含 timeline / 旁白 / 音频偏移）",
    description=(
        "返回完整时间线段落：旁白文本、`audio_offset`、`audio_duration`、媒体 URL。\n\n"
        "前端改 script / 拖动 audio 后，可再调本接口刷新状态。"
    ),
)
async def get_project(
    slug: str,
    session: BetaSession = Depends(require_beta_session),
) -> dict[str, Any]:
    if not _session_owns_slug(session, slug):
        raise HTTPException(status_code=404, detail="Project not found")
    root = await _ensure_workspace_root(slug)
    meta_path = root / "property.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    meta = _load(meta_path)
    ws = resolve_workspace_by_slug(slug, meta.get("video_path"))

    render = _load(ws.output_dir / "render_result_v2.json") or _load(ws.render_result_path)
    evaluation = _load(ws.evaluation_result_path)

    preview_path = ws.output_dir / "preview.mp4"
    draft_url = (
        _to_media_url(str(preview_path)) if preview_path.exists()
        else _to_media_url(str(ws.final_video_path)) if ws.final_video_path.exists()
        else _to_media_url(str(ws.final_video_v2_path)) if ws.final_video_v2_path.exists()
        else None
    )
    final_url = (
        _to_media_url(str(ws.final_video_v2_path)) if ws.final_video_v2_path.exists()
        else _to_media_url(str(ws.final_video_path)) if ws.final_video_path.exists()
        else None
    )
    # Browser should hit R2 directly — Railway /media proxy + cold hydrate is very slow.
    r2_final = _r2_presigned_final_for_slug(slug)
    if r2_final:
        final_url = r2_final
        # Never send a 100MB+ draft through Railway's /media static proxy.
        # When no separate lightweight preview exists on R2, the canonical
        # final is the fastest and most reliable draft playback source.
        if not draft_url or str(draft_url).startswith("/media/"):
            draft_url = r2_final
    from backend.configs import continuous_walkthrough_enabled, preserve_full_span_enabled

    return {
        "slug": slug,
        "video_name": meta.get("video_name", slug),
        "director_brief": meta.get("user_prompt", ""),
        "intent_meta": {
            "source": meta.get("intent_source", ""),
            "was_vague": meta.get("intent_was_vague", False),
            "original": meta.get("intent_original", ""),
            "narration_language": meta.get("narration_language", "en"),
        },
        "production": {
            "continuous_walkthrough": continuous_walkthrough_enabled(),
            "preserve_full_span": preserve_full_span_enabled(),
        },
        "stages": _stage_flags(ws),
        "thinking": _thinking_summary(ws),
        "timeline": _merge_timeline_segments(ws),
        "video": {
            "source_url": f"/api/studio/projects/{slug}/source",
            "draft_url": draft_url,
            "final_url": final_url,
            "duration": render.get("duration") or 0,
        },
        "evaluation": {
            "approved": evaluation.get("approved"),
            "overall_score": evaluation.get("overall_score"),
            "summary": evaluation.get("summary", ""),
            "scores": evaluation.get("scores", {}),
        } if evaluation else None,
        "jobs": [j.to_dict() for j in job_store.list_for_slug(slug)][-5:],
    }


@router.get(
    "/projects/{slug}/source",
    tags=[TAG_STUDIO_PROJECTS],
    summary="获取源带看视频",
    description="流式返回项目的原始 walkthrough 视频文件。",
)
async def get_source_video(slug: str):
    root = await _ensure_workspace_root(slug)
    meta = _load(root / "property.json")
    video_path = meta.get("video_path", "")
    candidates = [
        Path(video_path) if video_path else None,
        root / "source.mp4",
        root / "output" / "final_video_v2.mp4",
        root / "output" / "final_video.mp4",
    ]
    for path in candidates:
        if path and path.exists():
            return FileResponse(path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="Source video not found")


# ---------------------------------------------------------------------------
# Revisions — script / audio then export to regenerate final
# ---------------------------------------------------------------------------

class ReviseRequest(BaseModel):
    """修改旁白文案或音频起点后，会按依赖图重跑必要阶段（不是整条 pipeline）。"""

    change_type: Literal["script_update", "audio_offset"] = Field(
        ...,
        description=(
            "`script_update`：改旁白文案 → 重录该段 TTS + 更新字幕；"
            "`audio_offset`：改旁白相对画面起始偏移（秒）→ 保存 timing"
        ),
        examples=["script_update"],
    )
    segment_id: str = Field(..., description="时间线段落 ID", examples=["seg_003"])
    text: str = Field(
        "",
        description="仅 `script_update` 需要：新的旁白文案",
        examples=["这里是采光充足的客厅，落地窗引入自然光。"],
    )
    offset_seconds: float = Field(
        0.0,
        description="仅 `audio_offset` 需要：旁白相对该段画面起点的偏移（秒，可为负）",
        examples=[0.8],
    )


@router.post(
    "/projects/{slug}/revise",
    tags=[TAG_STUDIO_REVISE],
    summary="修改 Script 或 Audio 位置（局部重生成）",
    description=(
        "Studio 人机协作入口。改完后**不会**自动重渲整支成片，请再调 "
        "`POST /api/studio/projects/{slug}/export`。\n\n"
        "**改旁白文案**\n"
        "```json\n"
        '{ "change_type": "script_update", "segment_id": "seg_003", '
        '"text": "新的旁白……" }\n'
        "```\n"
        "→ 保存文案 → 重录该段语音 → 更新字幕。\n\n"
        "**改音频位置（offset）**\n"
        "```json\n"
        '{ "change_type": "audio_offset", "segment_id": "seg_003", '
        '"offset_seconds": 0.8 }\n'
        "```\n"
        "→ 保存旁白相对画面的起始偏移。\n\n"
        "返回 `job_id`，用 `GET /api/studio/jobs/{job_id}` 轮询直到 `done`。"
    ),
    response_description="`{ \"job_id\": \"...\" }`",
)
async def revise_project(
    slug: str,
    req: ReviseRequest,
    _session: str = Depends(require_write_session),
) -> dict[str, Any]:
    root = await _ensure_workspace_root(slug)
    meta = _load(root / "property.json")
    if not meta:
        raise HTTPException(status_code=404, detail="Project not found")
    ws = resolve_workspace_by_slug(slug, meta.get("video_path"))

    from backend.saas_jobs import attach_studio_saas_job, mark_job_completed, mark_job_failed

    saas = attach_studio_saas_job(
        slug,
        "script_update" if req.change_type == "script_update" else "audio_offset",
    )
    saas_job_id = saas[0] if saas else None
    on_progress = saas[1] if saas else None

    if req.change_type == "script_update":
        if not (req.text or "").strip():
            raise HTTPException(status_code=400, detail="text is required for script_update")
        job = job_store.create(
            slug, "script_update",
            [
                ("apply", "Saving your edit"),
                ("voice", "Re-recording narration"),
                ("subtitle", "Updating subtitle"),
            ],
            segment_id=req.segment_id,
            on_progress=on_progress,
        )

        async def _run_script() -> None:
            try:
                await orchestrator.run_script_update(job, ws, req.segment_id, req.text)
                if saas_job_id and job.status == "done":
                    mark_job_completed(saas_job_id, workspace_slug=slug)
                elif saas_job_id and job.status == "error":
                    mark_job_failed(saas_job_id, job.error or "script_update failed")
            except Exception as exc:  # noqa: BLE001
                if saas_job_id:
                    mark_job_failed(saas_job_id, str(exc))

        asyncio.create_task(_run_script())
    elif req.change_type == "audio_offset":
        job = job_store.create(
            slug, "audio_offset",
            [
                ("apply", "Saving narration timing"),
            ],
            segment_id=req.segment_id,
            on_progress=on_progress,
        )

        async def _run_offset() -> None:
            try:
                await orchestrator.run_audio_offset(
                    job, ws, req.segment_id, req.offset_seconds
                )
                if saas_job_id and job.status == "done":
                    mark_job_completed(saas_job_id, workspace_slug=slug)
                elif saas_job_id and job.status == "error":
                    mark_job_failed(saas_job_id, job.error or "audio_offset failed")
            except Exception as exc:  # noqa: BLE001
                if saas_job_id:
                    mark_job_failed(saas_job_id, str(exc))

        asyncio.create_task(_run_offset())
    else:
        raise HTTPException(status_code=400, detail=f"Unknown change_type: {req.change_type}")

    return {"job_id": job.id, "saas_job_id": saas_job_id}


@router.post(
    "/projects/{slug}/export",
    tags=[TAG_STUDIO_JOBS],
    summary="重新导出成片（应用 Script / Audio 修改）",
    description=(
        "在修改旁白或音频偏移之后调用，按当前磁盘上的 timeline / voice / editing "
        "状态重新渲染最终视频。\n\n"
        "推荐流程：\n"
        "1. `POST .../revise`（script 或 audio_offset）→ 等 job `done`\n"
        "2. `POST .../export` → 等 job `done`\n"
        "3. `GET /api/studio/projects/{slug}` 取 `video.final_url`"
    ),
)
async def export_project(
    slug: str,
    _session: str = Depends(require_write_session),
) -> dict[str, Any]:
    root = await _ensure_workspace_root(slug)
    meta = _load(root / "property.json")
    if not meta:
        raise HTTPException(status_code=404, detail="Project not found")
    ws = resolve_workspace_by_slug(slug, meta.get("video_path"))

    from backend.database import db
    from backend.saas_jobs import enqueue_job, mark_job_failed

    linked = db.find_project_by_workspace_slug(slug)

    job = job_store.create(
        slug,
        "export",
        [
            ("prepare", "Loading edited project"),
            ("render", "Rendering final video"),
            ("finalize", "Saving output"),
        ],
    )

    if linked:
        async def _queue_worker_export() -> None:
            saas_job_id: str | None = None
            try:
                job.status = "running"
                job.set_stage("prepare", "running", "Syncing edits to render worker")

                from backend.workspace_hydrate import resolve_workspace_r2_prefix
                from backend.workspace_sync import push_workspace_to_r2, refresh_workspace_from_r2

                prefix = resolve_workspace_r2_prefix(slug)
                if not prefix:
                    uid = linked.beta_account_id or linked.user_id or "anonymous"
                    prefix = f"users/{uid}/projects/{linked.project_id}/workspace"
                try:
                    from backend.workspace_paths import rewrite_workspace_media_paths

                    rewrite_workspace_media_paths(root)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.to_thread(push_workspace_to_r2, slug, prefix)
                meta2 = dict(linked.property_metadata or {})
                meta2["workspace_r2_prefix"] = prefix
                meta2["workspace_slug"] = slug
                linked.property_metadata = meta2
                db.save_project(linked)

                # Enqueue only after R2 has the latest edits (avoid worker race)
                saas_job = enqueue_job(
                    linked,
                    kind="export",
                    stage="Queued",
                    progress=0,
                    status="waiting",
                    input_url=linked.video_url or linked.video_path,
                )
                saas_job_id = saas_job.job_id

                job.set_stage("prepare", "done", "Queued for Mac Worker")
                job.set_stage("render", "running", "Waiting for render worker")

                for _ in range(3600):
                    if job.status == "cancelled":
                        if saas_job_id:
                            mark_job_failed(saas_job_id, "Cancelled by user")
                        return
                    saas_job = db.get_job(saas_job_id)
                    if not saas_job:
                        raise RuntimeError("SaaS export job disappeared")
                    prog = int(saas_job.progress or 0)
                    stage = (saas_job.stage or "").strip() or "Rendering"
                    if saas_job.status == "running":
                        job.set_stage("render", "running", stage)
                    if saas_job.status == "completed" or (
                        prog >= 100 and saas_job.status not in ("error", "waiting")
                    ):
                        job.set_stage("render", "done")
                        job.set_stage("finalize", "running", "Refreshing studio workspace")
                        await asyncio.to_thread(refresh_workspace_from_r2, slug, prefix)
                        job.set_stage("finalize", "done")
                        job.status = "done"
                        job.result = {
                            "final_video": saas_job.output_url or saas_job.final_video,
                        }
                        job.touch()
                        return
                    if saas_job.status == "error":
                        raise RuntimeError(saas_job.error or "Export worker failed")
                    await asyncio.sleep(2)

                raise RuntimeError("Export timed out waiting for worker")
            except Exception as exc:  # noqa: BLE001
                logger.exception("queued export failed for %s", slug)
                job.status = "error"
                job.error = str(exc)
                for s in job.stages:
                    if s.status == "running":
                        s.status = "error"
                job.touch()
                if saas_job_id:
                    mark_job_failed(saas_job_id, str(exc))

        asyncio.create_task(_queue_worker_export())
        return {"job_id": job.id, "saas_job_id": None}

    # Local / non-SaaS: render in-process (Mac Studio / dev)
    async def _run_export() -> None:
        try:
            await orchestrator.run_export(job, ws)
        except Exception as exc:  # noqa: BLE001
            logger.exception("local export failed")
            job.status = "error"
            job.error = str(exc)

    asyncio.create_task(_run_export())
    return {"job_id": job.id, "saas_job_id": None}


@router.get(
    "/jobs/{job_id}",
    tags=[TAG_STUDIO_JOBS],
    summary="查询 Studio 任务进度",
    description="轮询 revise / export / create_project 返回的 `job_id`。",
)
async def get_job(job_id: str, _session: str = Depends(require_beta_session)) -> dict[str, Any]:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.post(
    "/jobs/{job_id}/cancel",
    tags=[TAG_STUDIO_JOBS],
    summary="取消 Studio 任务",
    description="请求取消进行中的任务（在阶段检查点生效）。",
)
async def cancel_job(job_id: str, _session: str = Depends(require_write_session)) -> dict[str, Any]:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("done", "error", "cancelled"):
        return job.to_dict()
    job.request_cancel()
    if job.status in ("pending", "running"):
        job.mark_cancelled()
    return job.to_dict()


# ---------------------------------------------------------------------------
# New project intake — Upload + Director Brief
# ---------------------------------------------------------------------------

@router.post(
    "/projects",
    tags=[TAG_STUDIO_PROJECTS],
    summary="Studio 一键创建项目并跑完整 pipeline",
    description=(
        "上传视频 + brief + language，后台跑 Vision→…→Evaluation。"
        "与服务层 `/api/projects` + `/api/jobs` 不同，这是 Studio 页面用的一站式入口。"
    ),
)
async def create_project(
    video: UploadFile = File(..., description="带看视频"),
    brief: str = Form("", description="导演意图"),
    language: str = Form("en", description="旁白语言：en 或 zh"),
    _session: str = Depends(require_write_session),
) -> dict[str, Any]:
    from backend.workflows.user_intent import resolve_user_intent

    lang = (language or "en").strip().lower()
    if lang not in ("en", "zh"):
        raise HTTPException(status_code=400, detail="language must be 'en' or 'zh'")

    uploads_dir = PROJECT_ROOT / "storage" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    dest = uploads_dir / video.filename
    content = await video.read()
    dest.write_bytes(content)

    slug = slug_from_name(dest.name)
    resolved = resolve_user_intent(brief, interactive=False, language=lang)
    intent_meta = {
        "intent_source": resolved.source,
        "intent_was_vague": resolved.was_vague,
        "intent_original": resolved.original_prompt,
        "narration_language": lang,
    }

    job = job_store.create(
        slug, "create_project",
        [
            ("vision", "Understanding the property"),
            ("story", "Creating the story & narration"),
            ("editing", "Directing the edit"),
            ("evaluation", "Quality pass & final render"),
        ],
    )
    asyncio.create_task(
        orchestrator.run_create_project(job, dest, resolved.prompt, intent_meta)
    )
    return {
        "job_id": job.id,
        "slug": slug,
        "resolved_brief": resolved.prompt,
        "was_vague": resolved.was_vague,
        "narration_language": lang,
    }
