"""In-memory revision/production job tracker for the Director Studio API.

Not durable storage — sufficient for a single-process dev/demo backend.
Also emits numeric ``progress`` + optional ``on_progress`` for SaaS sync.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from backend.progress import JobCancelled, ProgressCallback, resolve_stage_progress

JobStatus = Literal["pending", "running", "done", "error", "cancelled"]


@dataclass
class StageState:
    name: str
    label: str
    status: JobStatus = "pending"
    detail: str = ""


@dataclass
class Job:
    id: str
    slug: str
    kind: str  # script_update | audio_offset | export | create_project
    segment_id: str = ""
    status: JobStatus = "pending"
    stages: list[StageState] = field(default_factory=list)
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # SaaS-style progress (0–100) + human stage label
    progress: int = 0
    stage_label: str = ""
    on_progress: Optional[ProgressCallback] = field(default=None, repr=False)

    def touch(self) -> None:
        self.updated_at = time.time()

    def request_cancel(self) -> bool:
        """Ask a running job to stop at the next checkpoint. Returns False if already terminal."""
        if self.status in ("done", "error", "cancelled"):
            return False
        self.cancel_requested = True
        self.touch()
        return True

    def mark_cancelled(self, detail: str = "Cancelled by user") -> None:
        self.status = "cancelled"
        self.error = detail
        for s in self.stages:
            if s.status in ("pending", "running"):
                s.status = "cancelled"
                s.detail = detail
        self.touch()

    def report_progress(self, stage: str, progress: int) -> None:
        """Update numeric progress and notify SaaS / Worker callback."""
        self.stage_label = stage
        self.progress = max(0, min(100, int(progress)))
        self.touch()
        if self.on_progress is not None:
            try:
                self.on_progress(stage, self.progress)
            except JobCancelled:
                raise
            except Exception:  # noqa: BLE001 — never break pipeline for progress I/O
                pass

    def set_stage(self, name: str, status: JobStatus, detail: str = "") -> None:
        for s in self.stages:
            if s.name == name:
                s.status = status
                s.detail = detail
                mapped = resolve_stage_progress(self.kind, name, status)
                if mapped:
                    pct, label = mapped
                    self.report_progress(label, pct)
                else:
                    self.touch()
                return

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "kind": self.kind,
            "segment_id": self.segment_id,
            "status": self.status,
            "stage": self.stage_label,
            "progress": self.progress,
            "stages": [
                {"name": s.name, "label": s.label, "status": s.status, "detail": s.detail}
                for s in self.stages
            ],
            "error": self.error,
            "result": self.result,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    """Process-local job registry."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(
        self,
        slug: str,
        kind: str,
        stage_defs: list[tuple[str, str]],
        segment_id: str = "",
        on_progress: Optional[ProgressCallback] = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            slug=slug,
            kind=kind,
            segment_id=segment_id,
            stages=[StageState(name=n, label=l) for n, l in stage_defs],
            on_progress=on_progress,
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_for_slug(self, slug: str) -> list[Job]:
        return [j for j in self._jobs.values() if j.slug == slug]


job_store = JobStore()
