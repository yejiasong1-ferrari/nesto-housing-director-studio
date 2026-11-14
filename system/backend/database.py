"""Nesto persistence: Supabase Postgres (SQLAlchemy) with in-memory fallback.

Set ``DATABASE_URL`` in ``.env`` to enable cloud DB. Without it, APIs still
work locally (Phase 2 memory store) so offline smoke tests keep passing.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Union

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.models import Job, Project, User
from backend.orm_models import (  # noqa: F401
    Base,
    BetaAccountRow,
    BetaSessionRow,
    InviteCodeRow,
    JobRow,
    ProjectRow,
    UserRow,
)
from backend.paths import REPO_ROOT

logger = logging.getLogger(__name__)

PROJECT_ROOT = REPO_ROOT
load_dotenv(PROJECT_ROOT / ".env")

PROJECTS_ROOT = PROJECT_ROOT / "storage" / "projects"
PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

# /api/jobs/next writes running/Claimed before the Worker reads the body.
# If that HTTP call times out, later polls correctly return null ("No jobs").
_PHANTOM_CLAIM_STAGES = frozenset({"", "claimed", "queued"})


def should_requeue_running_job(
    *,
    status: str,
    stage: str,
    progress: int,
    updated_at: Optional[datetime],
    created_at: Optional[datetime],
    now: Optional[datetime] = None,
    claimed_after_sec: int = 90,
    max_age_hours: int = 24,
) -> bool:
    """True when a running row was claimed but never actually processed."""
    if status != "running":
        return False
    clock = now or datetime.now(timezone.utc)
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at < clock - timedelta(hours=max_age_hours):
            return False
    stage_n = (stage or "").strip().lower()
    if int(progress or 0) > 5 or stage_n not in _PHANTOM_CLAIM_STAGES:
        return False
    return updated_at <= clock - timedelta(seconds=claimed_after_sec)

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
SUPABASE_URL = (
    os.getenv("SUPABASE_URL")
    or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    or ""
).strip()

engine = None
SessionLocal = None  # type: Optional[sessionmaker]

if DATABASE_URL:
    # Supabase pooler sometimes needs ssl; URI usually already includes it.
    # connect_timeout keeps Railway boot from hanging on a bad / slow DB.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args={"connect_timeout": 5},
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info("Nesto DB: SQLAlchemy engine ready (Supabase/Postgres)")
else:
    logger.warning(
        "Nesto DB: DATABASE_URL not set — using in-memory store. "
        "Add DATABASE_URL to .env and run supabase/migrations/001_nesto_phase3.sql"
    )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — only valid when DATABASE_URL is configured."""
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> str:
    """Create tables if engine is available. Returns backend mode label.

    Production (Railway) already has migrations applied — skip ``create_all``
    so a slow or IPv6-stuck Postgres handshake cannot block uvicorn listen
    and fail the 30s healthcheck.
    """
    if engine is None:
        return "memory"
    on_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
    if on_railway or os.getenv("SKIP_CREATE_ALL", "").strip() in {"1", "true", "yes"}:
        logger.info("Nesto DB: skip create_all (Railway / SKIP_CREATE_ALL)")
        return "supabase"
    Base.metadata.create_all(bind=engine)
    logger.info("Nesto DB: tables ensured (users, projects, jobs)")
    return "supabase"


def _row_to_user(row: UserRow) -> User:
    return User(user_id=row.id, email=row.email)


def _row_to_project(row: ProjectRow) -> Project:
    return Project(
        project_id=row.id,
        user_id=row.user_id,
        beta_account_id=getattr(row, "beta_account_id", None),
        title=row.title or "Untitled",
        brief=row.brief or "",
        language=row.language or "zh",
        status=row.status,  # type: ignore[arg-type]
        video_path=row.video_path,
        video_url=row.video_url,
        final_video=row.final_video,
        active_job_id=row.active_job_id,
        error=row.error or "",
        property_metadata=dict(row.property_metadata or {}),
    )


def _row_to_job(row: JobRow) -> Job:
    output = getattr(row, "output_url", None) or row.final_video
    return Job(
        job_id=row.id,
        project_id=row.project_id,
        kind=getattr(row, "kind", None) or "create",  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        stage=row.stage or "",
        progress=int(row.progress or 0),
        input_url=getattr(row, "input_url", None),
        output_url=output,
        final_video=output,
        error=row.error or "",
    )


def _apply_project(row: ProjectRow, project: Project) -> None:
    row.user_id = project.user_id
    if hasattr(row, "beta_account_id"):
        row.beta_account_id = project.beta_account_id
    row.title = project.title
    row.brief = project.brief
    row.language = project.language
    row.status = project.status
    row.video_path = project.video_path
    row.video_url = project.video_url
    row.final_video = project.final_video
    row.active_job_id = project.active_job_id
    row.error = project.error
    row.property_metadata = project.property_metadata or {}


def _apply_job(row: JobRow, job: Job) -> None:
    row.project_id = job.project_id
    if hasattr(row, "kind"):
        row.kind = job.kind or "create"
    row.status = "running" if job.status == "processing" else job.status
    row.stage = job.stage
    row.progress = job.progress
    output = job.output_url or job.final_video
    if hasattr(row, "input_url"):
        row.input_url = job.input_url
    if hasattr(row, "output_url"):
        row.output_url = output
    row.final_video = output
    row.error = job.error


class InMemoryDB:
    """Thread-safe process-local store (offline / test fallback)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.users: Dict[str, User] = {}
        self.projects: Dict[str, Project] = {}
        self.jobs: Dict[str, Job] = {}
        self.mode = "memory"

    def new_id(self, prefix: str = "") -> str:
        token = uuid.uuid4().hex[:12]
        return f"{prefix}{token}" if prefix else token

    def project_dir(self, project_id: str) -> Path:
        path = PROJECTS_ROOT / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_user(self, user: User) -> User:
        with self._lock:
            self.users[user.user_id] = user
            return user

    def get_user(self, user_id: str) -> Optional[User]:
        with self._lock:
            return self.users.get(user_id)

    def get_user_by_email(self, email: str) -> Optional[User]:
        with self._lock:
            for u in self.users.values():
                if u.email.lower() == email.lower():
                    return u
            return None

    def list_projects_for_user(self, user_id: str) -> list[Project]:
        with self._lock:
            return [p for p in self.projects.values() if p.user_id == user_id]

    def list_projects_for_beta_account(self, beta_account_id: str) -> list[Project]:
        with self._lock:
            return [
                p
                for p in self.projects.values()
                if p.beta_account_id == beta_account_id
            ]

    def list_all_projects(self, limit: int = 200) -> list[Project]:
        with self._lock:
            items = list(self.projects.values())
        items.sort(key=lambda p: p.project_id, reverse=True)
        return items[:limit]

    def create_project(self, project: Project) -> Project:
        with self._lock:
            self.projects[project.project_id] = project
            return project

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._lock:
            return self.projects.get(project_id)

    def save_project(self, project: Project) -> Project:
        with self._lock:
            self.projects[project.project_id] = project
            return project

    def create_job(self, job: Job) -> Job:
        with self._lock:
            self.jobs[job.job_id] = job
            return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self.jobs.get(job_id)

    def save_job(self, job: Job) -> Job:
        with self._lock:
            self.jobs[job.job_id] = job
            return job

    def list_jobs(self, status: Optional[str] = None) -> list[Job]:
        with self._lock:
            jobs = list(self.jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs

    def list_jobs_for_project(self, project_id: str) -> list[Job]:
        with self._lock:
            return [j for j in self.jobs.values() if j.project_id == project_id]

    def requeue_stale_running_jobs(self) -> int:
        """No-op in memory mode — tests claim instantly."""
        return 0

    def claim_next_job(self) -> Optional[tuple[Job, Project]]:
        """Atomically claim the oldest waiting job → running."""
        with self._lock:
            waiting = [j for j in self.jobs.values() if j.status == "waiting"]
            if not waiting:
                return None
            # FIFO by job_id is weak; fine for memory mode
            waiting.sort(key=lambda j: j.job_id)
            job = waiting[0]
            project = self.projects.get(job.project_id)
            if not project:
                return None
            job.status = "running"
            job.stage = "Claimed"
            job.progress = max(job.progress, 1)
            project.status = "processing"
            project.active_job_id = job.job_id
            self.jobs[job.job_id] = job
            self.projects[project.project_id] = project
            return job, project

    def find_project_by_workspace_slug(self, slug: str) -> Optional[Project]:
        with self._lock:
            for p in self.projects.values():
                meta = p.property_metadata or {}
                if meta.get("workspace_slug") == slug:
                    return p
            return None


class SqlAlchemyDB:
    """Persists Users / Projects / Jobs to Supabase Postgres."""

    def __init__(self) -> None:
        if SessionLocal is None:
            raise RuntimeError("SQLAlchemy session factory not configured")
        self.mode = "supabase"

    def new_id(self, prefix: str = "") -> str:
        token = uuid.uuid4().hex[:12]
        return f"{prefix}{token}" if prefix else token

    def project_dir(self, project_id: str) -> Path:
        path = PROJECTS_ROOT / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_user(self, user: User) -> User:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = UserRow(id=user.user_id, email=user.email)
            session.add(row)
            session.commit()
            return user

    def get_user(self, user_id: str) -> Optional[User]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(UserRow, user_id)
            if not row:
                return None
            return _row_to_user(row)

    def get_user_by_email(self, email: str) -> Optional[User]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = (
                session.query(UserRow)
                .filter(UserRow.email == email)
                .one_or_none()
            )
            if not row:
                return None
            return _row_to_user(row)

    def list_projects_for_user(self, user_id: str) -> list[Project]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = (
                session.query(ProjectRow)
                .filter(ProjectRow.user_id == user_id)
                .order_by(ProjectRow.created_at.desc())
                .all()
            )
            return [_row_to_project(r) for r in rows]

    def list_projects_for_beta_account(self, beta_account_id: str) -> list[Project]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = (
                session.query(ProjectRow)
                .filter(ProjectRow.beta_account_id == beta_account_id)
                .order_by(ProjectRow.created_at.desc())
                .all()
            )
            return [_row_to_project(r) for r in rows]

    def list_all_projects(self, limit: int = 200) -> list[Project]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = (
                session.query(ProjectRow)
                .order_by(ProjectRow.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_project(r) for r in rows]

    def create_project(self, project: Project) -> Project:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = ProjectRow(id=project.project_id)
            _apply_project(row, project)
            session.add(row)
            session.commit()
            return project

    def get_project(self, project_id: str) -> Optional[Project]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(ProjectRow, project_id)
            return _row_to_project(row) if row else None

    def save_project(self, project: Project) -> Project:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(ProjectRow, project.project_id)
            if not row:
                row = ProjectRow(id=project.project_id)
                session.add(row)
            _apply_project(row, project)
            session.commit()
            return project

    def create_job(self, job: Job) -> Job:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = JobRow(id=job.job_id)
            _apply_job(row, job)
            session.add(row)
            session.commit()
            return job

    def get_job(self, job_id: str) -> Optional[Job]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(JobRow, job_id)
            return _row_to_job(row) if row else None

    def save_job(self, job: Job) -> Job:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(JobRow, job.job_id)
            if not row:
                row = JobRow(id=job.job_id)
                session.add(row)
            _apply_job(row, job)
            session.commit()
            return job

    def list_jobs(self, status: Optional[str] = None) -> list[Job]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            q = session.query(JobRow).order_by(JobRow.created_at.asc())
            if status:
                q = q.filter(JobRow.status == status)
            return [_row_to_job(r) for r in q.all()]

    def list_jobs_for_project(self, project_id: str) -> list[Job]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = (
                session.query(JobRow)
                .filter(JobRow.project_id == project_id)
                .order_by(JobRow.created_at.desc())
                .all()
            )
            return [_row_to_job(r) for r in rows]

    def requeue_stale_running_jobs(
        self,
        *,
        claimed_after_sec: int = 90,
        max_age_hours: int = 24,
    ) -> int:
        """Return phantom-claimed jobs to ``waiting``.

        ``/api/jobs/next`` marks a row running before the Worker receives the
        payload. If Railway is slow and the Worker times out, the job is stuck
        as Claimed and later polls print ``No jobs``. Restarting Railway or the
        Worker does not delete these rows — they just have to be waiting again.

        Only recent Claimed rows are touched. Month-old abandoned jobs stay
        put so they cannot jump in front of today's testers.
        """
        assert SessionLocal is not None
        now = datetime.now(timezone.utc)
        created_after = now - timedelta(hours=max_age_hours)
        count = 0
        with SessionLocal() as session:
            rows = (
                session.query(JobRow)
                .filter(JobRow.status == "running")
                .filter(JobRow.created_at >= created_after)
                .all()
            )
            for row in rows:
                if not should_requeue_running_job(
                    status=row.status,
                    stage=row.stage or "",
                    progress=int(row.progress or 0),
                    updated_at=row.updated_at,
                    created_at=row.created_at,
                    now=now,
                    claimed_after_sec=claimed_after_sec,
                    max_age_hours=max_age_hours,
                ):
                    continue
                logger.info(
                    "Requeued stale running job %s (stage=%s progress=%s)",
                    row.id,
                    row.stage,
                    int(row.progress or 0),
                )
                row.status = "waiting"
                row.stage = "Queued"
                row.progress = 0
                row.error = ""
                proj = session.get(ProjectRow, row.project_id)
                if proj and proj.status in ("processing", "queued", "created"):
                    proj.status = "queued"
                    proj.active_job_id = row.id
                count += 1
            if count:
                session.commit()
        return count

    def claim_next_job(self) -> Optional[tuple[Job, Project]]:
        """Claim oldest waiting job with row lock (SKIP LOCKED when available)."""
        assert SessionLocal is not None
        with SessionLocal() as session:
            try:
                session.execute(text("SET LOCAL statement_timeout = 5000"))
            except Exception:
                logger.debug("statement_timeout not supported on this connection")
            q = (
                session.query(JobRow)
                .filter(JobRow.status == "waiting")
                .order_by(JobRow.created_at.asc())
            )
            try:
                row = q.with_for_update(skip_locked=True).first()
            except Exception:  # noqa: BLE001 — some poolers may not support SKIP LOCKED
                row = q.with_for_update().first()
            if not row:
                return None
            proj_row = session.get(ProjectRow, row.project_id)
            if not proj_row:
                return None
            row.status = "running"
            row.stage = "Claimed"
            row.progress = max(int(row.progress or 0), 1)
            proj_row.status = "processing"
            proj_row.active_job_id = row.id
            session.commit()
            session.refresh(row)
            session.refresh(proj_row)
            return _row_to_job(row), _row_to_project(proj_row)

    def find_project_by_workspace_slug(self, slug: str) -> Optional[Project]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = session.query(ProjectRow).all()
            for row in rows:
                meta = dict(row.property_metadata or {})
                if meta.get("workspace_slug") == slug:
                    return _row_to_project(row)
            return None


def build_store() -> Union[InMemoryDB, SqlAlchemyDB]:
    if engine is not None:
        return SqlAlchemyDB()
    return InMemoryDB()


db = build_store()  # type: Union[InMemoryDB, SqlAlchemyDB]
