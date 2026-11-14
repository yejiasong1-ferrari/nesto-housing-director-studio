"""One-shot: upload an existing Mac workspace to R2 and link it on the SaaS project.

Usage (from repo root)::

    PYTHONPATH=system:system/worker python system/worker/backfill_workspace.py \\
      --slug 75f5878b46d0-6 \\
      --project-id proj_c62b0edcd943 \\
      --user-id user_634c061a0520
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_WORKER_DIR = Path(__file__).resolve().parent
_SYSTEM_DIR = _WORKER_DIR.parent
_REPO_ROOT = _SYSTEM_DIR.parent
for p in (_SYSTEM_DIR, _WORKER_DIR, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_WORKER_DIR / ".env", override=True)

from workspace_upload import upload_studio_workspace  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument(
        "--source",
        default="",
        help="Optional source mp4 path (defaults to property.json video_path)",
    )
    args = parser.parse_args()

    ws = _REPO_ROOT / "storage" / "properties" / args.slug
    if not (ws / "property.json").exists():
        raise SystemExit(f"Workspace not found: {ws}")

    source = Path(args.source) if args.source else None
    if source is None:
        import json

        meta = json.loads((ws / "property.json").read_text(encoding="utf-8"))
        vp = meta.get("video_path") or ""
        if vp and Path(vp).exists():
            source = Path(vp)

    job = {"user_id": args.user_id, "project_id": args.project_id}
    print(f"Uploading {ws} …")
    prefix = upload_studio_workspace(job, ws, source_video=source)
    if not prefix:
        raise SystemExit("Upload produced no files")
    print(f"R2 prefix: {prefix}")

    from backend.database import db

    project = db.get_project(args.project_id)
    if not project:
        raise SystemExit(f"Project not found in DB: {args.project_id}")
    meta = dict(project.property_metadata or {})
    meta["workspace_slug"] = args.slug
    meta["workspace_r2_prefix"] = prefix
    project.property_metadata = meta
    project.status = "completed"
    db.save_project(project)

    if project.active_job_id:
        job_row = db.get_job(project.active_job_id)
        if job_row and job_row.status != "completed":
            job_row.status = "completed"
            job_row.stage = "Completed"
            job_row.progress = 100
            db.save_job(job_row)
            print(f"Fixed job {job_row.job_id} → completed")

    print(f"Linked project {args.project_id} → workspace {args.slug}")


if __name__ == "__main__":
    main()
