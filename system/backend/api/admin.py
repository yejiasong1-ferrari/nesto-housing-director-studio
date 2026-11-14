"""Admin Console API — independent of beta_account_id History scoping.

Auth: X-Admin-Key == INVITE_ADMIN_KEY (same key as invite create/list).
Never weaken GET /api/projects for admin — all cross-tenant reads live here.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from backend.database import db
from backend.invite_db import (
    create_view_as_session,
    force_logout_account,
    invite_db,
    reactivate_account,
    revoke_account,
    session_is_online,
    utcnow,
)
from backend.r2 import generate_download_url, parse_r2_uri, r2_configured
from backend.tools.property_workspace import STORAGE_ROOT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])

ARTIFACT_REL_PATHS = {
    "vkb": "vision/vision_knowledge_base.json",
    "planner": "planner/planner_output.json",
    "script": "script/script_output.json",
    "timeline": "timeline/timeline_output.json",
    "voice": "voice/voice_execution.json",
    "editing": "editing/editing_plan.json",
    "render": "output/render_result.json",
    "evaluation": "evaluation/evaluation_result.json",
}


def _admin_ok(x_admin_key: Optional[str]) -> bool:
    expected = (os.getenv("INVITE_ADMIN_KEY") or "").strip()
    if not expected:
        from backend.invite_db import invite_db as store

        return type(store).__name__ == "_MemoryInviteStore"
    return bool(x_admin_key and x_admin_key.strip() == expected)


async def require_admin_key(
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> str:
    if not _admin_ok(x_admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key or ""


def _fmt(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _presign_video(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return None
    raw = str(uri).strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("r2://"):
        if not r2_configured():
            return None
        try:
            _bucket, key = parse_r2_uri(raw)
            return generate_download_url(key, expires_in=3600)
        except Exception as exc:  # noqa: BLE001
            logger.warning("presign failed for %s: %s", raw, exc)
            return None
    # Bare R2 object key
    if "/" in raw and not raw.startswith("/") and r2_configured():
        try:
            return generate_download_url(raw.lstrip("/"), expires_in=3600)
        except Exception as exc:  # noqa: BLE001
            logger.warning("presign bare key failed for %s: %s", raw, exc)
            return None
    path = Path(raw)
    if path.exists():
        return None
    return None


def _resolve_final_uri(project, job=None, project_jobs: Optional[list] = None) -> Optional[str]:
    """Prefer project.final_video, then active job, then any completed job output."""
    if project.final_video:
        return str(project.final_video)
    if job and (job.output_url or job.final_video):
        return str(job.output_url or job.final_video)
    for j in project_jobs or []:
        if j.status == "completed" and (j.output_url or j.final_video):
            return str(j.output_url or j.final_video)
    return None


def _remaining_seconds(expires_at: Optional[datetime]) -> Optional[int]:
    if not expires_at:
        return None
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return max(0, int((exp - utcnow()).total_seconds()))


class CreateInviteBody(BaseModel):
    code: Optional[str] = None


class ExtendInviteBody(BaseModel):
    hours: float = Field(3.0, ge=0.1, le=168.0)


class ViewAsBody(BaseModel):
    ttl_hours: float = Field(1.0, ge=0.1, le=12.0)


@router.get("/ping", summary="Auth check (fast)")
async def admin_ping(_key: str = Depends(require_admin_key)) -> dict:
    """Lightweight key validation for Admin Console login."""
    return {"ok": True, "service": "admin"}


@router.get("/users", summary="List all beta accounts")
async def admin_list_users(_key: str = Depends(require_admin_key)) -> dict:
    accounts = invite_db.list_accounts(500)
    projects = db.list_all_projects(500)
    by_account: dict[str, list] = {}
    for p in projects:
        aid = p.beta_account_id or ""
        by_account.setdefault(aid, []).append(p)

    users = []
    for a in accounts:
        owned = by_account.get(a.id, [])
        videos = sum(1 for p in owned if p.final_video)
        sessions = invite_db.list_sessions_for_account(a.id)
        live = [s for s in sessions if session_is_online(s) and not s.read_only]
        live_sess = live[0] if live else None
        active_job_stage = None
        for p in owned:
            if not p.active_job_id:
                continue
            job = db.get_job(p.active_job_id)
            if job and job.status in ("waiting", "running"):
                active_job_stage = job.stage or job.status
                break
        current_stage = None
        if live_sess and live_sess.current_stage:
            current_stage = live_sess.current_stage
        elif active_job_stage:
            current_stage = active_job_stage
        users.append(
            {
                "id": a.id,
                "invite_code": a.invite_code,
                "status": a.status or "active",
                "device_id": a.device_id,
                "created_at": _fmt(a.created_at),
                "expires_at": _fmt(a.expires_at),
                "revoked_at": _fmt(a.revoked_at),
                "remaining_seconds": _remaining_seconds(a.expires_at),
                "project_count": len(owned),
                "video_count": videos,
                "online": bool(live_sess),
                "current_page": live_sess.current_page if live_sess else None,
                "current_project": live_sess.current_project if live_sess else None,
                "current_stage": current_stage,
            }
        )
    return {"users": users}


@router.get("/users/{account_id}", summary="Beta account detail")
async def admin_get_user(
    account_id: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    account = invite_db.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    owned = [
        p for p in db.list_all_projects(2000) if p.beta_account_id == account_id
    ]
    sessions = invite_db.list_sessions_for_account(account_id)
    return {
        "id": account.id,
        "invite_code": account.invite_code,
        "status": account.status or "active",
        "device_id": account.device_id,
        "created_at": _fmt(account.created_at),
        "expires_at": _fmt(account.expires_at),
        "revoked_at": _fmt(account.revoked_at),
        "remaining_seconds": _remaining_seconds(account.expires_at),
        "project_count": len(owned),
        "video_count": sum(1 for p in owned if p.final_video),
        "online": any(session_is_online(s) and not s.read_only for s in sessions),
        "sessions": [
            {
                "id": s.id,
                "read_only": s.read_only,
                "online": session_is_online(s),
                "heartbeat_at": _fmt(s.heartbeat_at),
                "current_page": s.current_page,
                "current_project": s.current_project,
                "current_stage": s.current_stage,
                "expires_at": _fmt(s.expires_at),
            }
            for s in sessions
        ],
        "projects": [
            {
                "project_id": p.project_id,
                "title": p.title,
                "status": p.status,
                "final_video": p.final_video,
            }
            for p in owned
        ],
    }


@router.post("/users/{account_id}/force-logout", summary="Force logout + cancel active jobs")
async def admin_force_logout_user(
    account_id: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    """Sign the user out and stop waiting/running work. Invite code stays as-is."""
    result = force_logout_account(account_id)
    if not result:
        raise HTTPException(status_code=404, detail="Account not found")
    account, cancelled = result
    return {
        "ok": True,
        "id": account.id,
        "status": account.status,
        "jobs_cancelled": cancelled,
    }


@router.post("/users/{account_id}/revoke", summary="Force logout + cancel active jobs (alias)")
async def admin_revoke_user(
    account_id: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    """Alias of force-logout for older admin clients."""
    result = force_logout_account(account_id)
    if not result:
        raise HTTPException(status_code=404, detail="Account not found")
    account, cancelled = result
    return {
        "ok": True,
        "id": account.id,
        "status": account.status,
        "jobs_cancelled": cancelled,
    }


@router.post("/users/{account_id}/reactivate", summary="Reactivate revoked account")
async def admin_reactivate_user(
    account_id: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    account = reactivate_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True, "id": account.id, "status": account.status}


@router.post("/users/{account_id}/view-as", summary="Create read-only View-as session")
async def admin_view_as(
    account_id: str,
    body: ViewAsBody = ViewAsBody(),
    _key: str = Depends(require_admin_key),
) -> dict:
    try:
        sess = create_view_as_session(account_id, ttl_hours=body.ttl_hours)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "token": sess.token,
        "beta_account_id": sess.beta_account_id,
        "read_only": True,
        "expires_at": _fmt(sess.expires_at),
    }


@router.get("/projects", summary="List all projects (no account filter)")
async def admin_list_projects(
    beta_account_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    _key: str = Depends(require_admin_key),
) -> dict:
    items = db.list_all_projects(max(1, min(limit, 500)))
    if beta_account_id:
        items = [p for p in items if p.beta_account_id == beta_account_id]
    if status:
        items = [p for p in items if p.status == status]

    out = []
    for p in items:
        job = db.get_job(p.active_job_id) if p.active_job_id else None
        account = invite_db.get_account(p.beta_account_id) if p.beta_account_id else None
        meta = p.property_metadata or {}
        out.append(
            {
                "project_id": p.project_id,
                "title": p.title,
                "status": p.status,
                "brief": (p.brief or "")[:200],
                "beta_account_id": p.beta_account_id,
                "invite_code": account.invite_code if account else None,
                "final_video": p.final_video,
                "has_final": bool(p.final_video),
                "download_url": None,  # presign only on project detail
                "active_job_id": p.active_job_id,
                "stage": job.stage if job else "",
                "progress": job.progress if job else 0,
                "workspace_slug": meta.get("workspace_slug"),
                "error": p.error or (job.error if job else "") or "",
            }
        )
    return {"projects": out}


def _load_local_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _artifact_summary(slug: Optional[str]) -> dict[str, Any]:
    if not slug:
        return {"available": [], "slug": None}
    root = STORAGE_ROOT / slug
    available = []
    for name, rel in ARTIFACT_REL_PATHS.items():
        if (root / rel).exists():
            available.append(name)
    return {"available": available, "slug": slug, "local": root.exists()}


@router.get("/projects/{project_id}", summary="Project detail + video + artifact index")
async def admin_get_project(
    project_id: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    job = db.get_job(project.active_job_id) if project.active_job_id else None
    account = (
        invite_db.get_account(project.beta_account_id)
        if project.beta_account_id
        else None
    )
    meta = project.property_metadata or {}
    slug = meta.get("workspace_slug")
    jobs = db.list_jobs_for_project(project_id)
    video_uri = _resolve_final_uri(project, job, jobs)

    return {
        "project_id": project.project_id,
        "title": project.title,
        "brief": project.brief,
        "language": project.language,
        "status": project.status,
        "beta_account_id": project.beta_account_id,
        "invite_code": account.invite_code if account else None,
        "owner_status": account.status if account else None,
        "final_video": project.final_video,
        "video_url": video_uri,
        "download_url": _presign_video(video_uri),
        "active_job_id": project.active_job_id,
        "stage": job.stage if job else "",
        "progress": 100 if project.status == "completed" else (job.progress if job else 0),
        "error": project.error or (job.error if job else "") or "",
        "workspace_slug": slug,
        "workspace_r2_prefix": meta.get("workspace_r2_prefix"),
        "artifacts": _artifact_summary(slug),
        "jobs": [
            {
                "job_id": j.job_id,
                "kind": j.kind,
                "status": j.status,
                "stage": j.stage,
                "progress": j.progress,
                "error": j.error,
                "output_url": j.output_url or j.final_video,
            }
            for j in jobs
        ],
        "property_metadata": meta,
    }


@router.get(
    "/projects/{project_id}/media",
    summary="Fast final-video presign only",
)
async def admin_project_media(
    project_id: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    job = db.get_job(project.active_job_id) if project.active_job_id else None
    jobs = db.list_jobs_for_project(project_id)
    video_uri = _resolve_final_uri(project, job, jobs)
    url = _presign_video(video_uri)
    if not url:
        raise HTTPException(
            status_code=404,
            detail=f"No playable final video (uri={video_uri!r})",
        )
    return {
        "project_id": project_id,
        "video_url": video_uri,
        "download_url": url,
    }


@router.get(
    "/projects/{project_id}/stream",
    summary="302 redirect to final video (for <video src>, avoids CORS)",
)
async def admin_project_stream(
    project_id: str,
    admin_key: Optional[str] = Query(default=None, alias="admin_key"),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    if not _admin_ok(admin_key or x_admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    job = db.get_job(project.active_job_id) if project.active_job_id else None
    jobs = db.list_jobs_for_project(project_id)
    video_uri = _resolve_final_uri(project, job, jobs)
    url = _presign_video(video_uri)
    if not url:
        raise HTTPException(status_code=404, detail="No playable final video")
    return RedirectResponse(url=url, status_code=302)


@router.get(
    "/projects/{project_id}/artifacts/{name}",
    summary="Read pipeline artifact JSON (debug)",
)
async def admin_get_artifact(
    project_id: str,
    name: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    if name not in ARTIFACT_REL_PATHS:
        raise HTTPException(status_code=400, detail=f"Unknown artifact: {name}")
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = project.property_metadata or {}
    slug = meta.get("workspace_slug")
    if not slug:
        raise HTTPException(status_code=404, detail="No workspace_slug on project")

    rel = ARTIFACT_REL_PATHS[name]
    local = STORAGE_ROOT / slug / rel
    data = _load_local_json(local)
    if data is not None:
        return {"name": name, "source": "local", "data": data}

    # Try single-file pull from R2 without full workspace hydrate
    prefix = (meta.get("workspace_r2_prefix") or "").strip().rstrip("/")
    if not prefix and project.beta_account_id:
        prefix = f"users/{project.beta_account_id}/projects/{project.project_id}/workspace"
    if prefix and r2_configured():
        key = f"{prefix}/{rel}"
        try:
            from backend.r2 import download_object, r2_public_uri
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            download_object(r2_public_uri(key), tmp_path)
            data = _load_local_json(tmp_path)
            tmp_path.unlink(missing_ok=True)
            if data is not None:
                return {"name": name, "source": "r2", "data": data}
        except Exception as exc:  # noqa: BLE001
            logger.warning("artifact r2 fetch failed %s: %s", key, exc)

    raise HTTPException(status_code=404, detail=f"Artifact {name} not found")


@router.get("/jobs", summary="List all jobs")
async def admin_list_jobs(
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 200,
    _key: str = Depends(require_admin_key),
) -> dict:
    jobs = db.list_jobs(status=status)
    if project_id:
        jobs = [j for j in jobs if j.project_id == project_id]
    jobs = list(reversed(jobs))[: max(1, min(limit, 500))]
    out = []
    for j in jobs:
        p = db.get_project(j.project_id)
        account = (
            invite_db.get_account(p.beta_account_id)
            if p and p.beta_account_id
            else None
        )
        out.append(
            {
                "job_id": j.job_id,
                "project_id": j.project_id,
                "title": p.title if p else None,
                "beta_account_id": p.beta_account_id if p else None,
                "invite_code": account.invite_code if account else None,
                "kind": j.kind,
                "status": j.status,
                "stage": j.stage,
                "progress": j.progress,
                "error": j.error,
                "output_url": j.output_url or j.final_video,
                "has_final": bool(j.output_url or j.final_video or (p and p.final_video)),
                "download_url": None,
            }
        )
    return {"jobs": out}


@router.get("/invites", summary="List invite codes")
async def admin_list_invites(
    limit: int = 50,
    light: bool = False,
    _key: str = Depends(require_admin_key),
) -> dict:
    items = invite_db.list_codes(max(1, min(limit, 200)))
    if light:
        return {
            "codes": [
                {
                    "code": c.code,
                    "status": c.status,
                    "device_id": c.device_id,
                    "activated_at": _fmt(c.activated_at),
                    "expires_at": _fmt(c.expires_at),
                    "created_at": _fmt(c.created_at),
                    "remaining_seconds": _remaining_seconds(c.expires_at),
                    "beta_account_id": None,
                    "account_status": None,
                    "project_count": 0,
                    "video_count": 0,
                    "online": False,
                }
                for c in items
            ]
        }
    accounts = {a.invite_code_id: a for a in invite_db.list_accounts(500)}
    projects = db.list_all_projects(500)
    codes = []
    for c in items:
        account = accounts.get(c.id)
        owned = (
            [p for p in projects if p.beta_account_id == account.id] if account else []
        )
        sessions = (
            invite_db.list_sessions_for_account(account.id) if account else []
        )
        online = any(session_is_online(s) and not s.read_only for s in sessions)
        codes.append(
            {
                "code": c.code,
                "status": c.status,
                "device_id": c.device_id,
                "activated_at": _fmt(c.activated_at),
                "expires_at": _fmt(c.expires_at),
                "created_at": _fmt(c.created_at),
                "remaining_seconds": _remaining_seconds(c.expires_at),
                "beta_account_id": account.id if account else None,
                "account_status": account.status if account else None,
                "project_count": len(owned),
                "video_count": sum(1 for p in owned if p.final_video),
                "online": online,
            }
        )
    return {"codes": codes}


@router.post("/invites", summary="Create invite code")
async def admin_create_invite(
    body: CreateInviteBody = CreateInviteBody(),
    _key: str = Depends(require_admin_key),
) -> dict:
    try:
        inv = invite_db.create_code(body.code)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"code": inv.code, "status": inv.status, "created_at": _fmt(inv.created_at)}


@router.post("/invites/{code}/extend", summary="Extend invite expiry")
async def admin_extend_invite(
    code: str,
    body: ExtendInviteBody = ExtendInviteBody(),
    _key: str = Depends(require_admin_key),
) -> dict:
    inv = invite_db.get_by_code(code)
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    base = inv.expires_at or utcnow()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    if base < utcnow():
        base = utcnow()
    inv.expires_at = base + timedelta(hours=body.hours)
    if inv.status == "expired":
        inv.status = "used" if inv.device_id else "active"
    invite_db.save_invite(inv)
    account = invite_db.get_account_by_invite_id(inv.id)
    if account:
        account.expires_at = inv.expires_at
        if account.status == "revoked":
            pass  # keep revoked until explicit reactivate
        invite_db.save_account(account)
    return {
        "code": inv.code,
        "status": inv.status,
        "expires_at": _fmt(inv.expires_at),
        "remaining_seconds": _remaining_seconds(inv.expires_at),
    }


@router.post("/invites/{code}/revoke", summary="Revoke invite code (no longer usable)")
async def admin_revoke_invite(
    code: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    """Invalidate the invite code and kick any linked account (jobs left alone)."""
    inv = invite_db.get_by_code(code)
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    inv.status = "expired"
    inv.expires_at = utcnow()
    invite_db.save_invite(inv)
    account = invite_db.get_account_by_invite_id(inv.id)
    kicked = False
    if account:
        if (account.status or "active") != "revoked":
            revoke_account(account.id)
        kicked = True
    return {
        "ok": True,
        "code": inv.code,
        "status": inv.status,
        "account_revoked": kicked,
    }


@router.delete("/invites/{code}", summary="Delete unused invite code")
async def admin_delete_invite(
    code: str,
    _key: str = Depends(require_admin_key),
) -> dict:
    inv = invite_db.get_by_code(code)
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    if inv.status == "used":
        raise HTTPException(
            status_code=409,
            detail="Invite already used — revoke instead of delete",
        )
    ok = invite_db.delete_invite(code)
    return {"ok": ok, "code": code.upper()}
