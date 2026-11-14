"""Phase 2 API tests — projects / upload / jobs with mocked generate_video."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.database import InMemoryDB
from backend.invite_db import _MemoryInviteStore, verify_and_activate
from backend.main import app


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = InMemoryDB()
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)

    def _project_dir(project_id: str) -> Path:
        path = root / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(store, "project_dir", _project_dir)
    for target in (
        "backend.database.db",
        "backend.api.projects.db",
        "backend.api.upload.db",
        "backend.api.jobs.db",
        "backend.api.users.db",
        "backend.saas_jobs.db",
    ):
        monkeypatch.setattr(target, store)

    mem = _MemoryInviteStore()
    monkeypatch.setattr("backend.invite_db.invite_db", mem)
    monkeypatch.setattr("backend.api.invite.invite_db", mem)
    mem.create_code("NESTO-TEST01")
    sess, _, _ = verify_and_activate("NESTO-TEST01", device_id="test-device")

    with TestClient(app) as client:
        client.cookies.set("nesto_session", sess.token)
        yield client, store, tmp_path


def test_home_and_health(api):
    client, _, _ = api
    assert client.get("/").json()["message"] == "Nesto API running"
    assert client.get("/health").json()["status"] == "ok"


def test_create_project(api):
    client, store, _ = api
    res = client.post(
        "/api/projects",
        json={
            "brief": "Highlight kitchen",
            "language": "English",
            "title": "Luxury House",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "created"
    assert body["project_id"].startswith("proj_")
    assert body["beta_account_id"]
    assert body["title"] == "Luxury House"
    proj = store.get_project(body["project_id"])
    assert proj.language == "en"
    assert proj.beta_account_id == body["beta_account_id"]


def test_history_lists_own_projects(api):
    client, store, _ = api
    created = client.post(
        "/api/projects",
        json={"brief": "a", "language": "zh", "title": "Mine"},
    ).json()
    p = store.get_project(created["project_id"])
    p.status = "completed"
    p.final_video = "r2://x/final.mp4"
    store.save_project(p)
    listed = client.get("/api/projects").json()
    assert any(x["project_id"] == created["project_id"] for x in listed)


def test_create_user(api):
    client, _, _ = api
    res = client.post("/api/users", json={"email": "sam@example.com"})
    assert res.status_code == 200
    assert res.json()["status"] == "created"
    again = client.post("/api/users", json={"email": "sam@example.com"})
    assert again.json()["status"] == "exists"


def test_job_runs_generate_video(api, monkeypatch: pytest.MonkeyPatch):
    import asyncio

    client, store, tmp_path = api

    pid = client.post(
        "/api/projects",
        json={"brief": "natural light", "language": "zh"},
    ).json()["project_id"]

    up = client.post(
        "/api/upload",
        data={"project_id": pid},
        files={"file": ("house.mp4", b"fake-video", "video/mp4")},
    )
    assert up.status_code == 200
    assert store.get_project(pid).video_path

    pipeline_out = tmp_path / "pipeline_out.mp4"
    pipeline_out.write_bytes(b"mp4")

    async def _fake_generate(video_path, brief, language, on_progress=None):
        assert Path(video_path).exists()
        assert language == "zh"
        assert "light" in brief
        return pipeline_out

    monkeypatch.setattr("backend.ai_director.generate_video", _fake_generate)

    # Avoid fire-and-forget; run the worker directly after enqueue
    from backend.api import jobs as jobs_api

    monkeypatch.setattr(jobs_api, "start_job_task", lambda job: None)

    job_body = client.post("/api/jobs", json={"project_id": pid}).json()
    job_id = job_body["job_id"]
    assert job_body["status"] == "waiting"

    asyncio.run(jobs_api.run_generate_video_job(job_id))

    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["status"] == "completed", status
    assert Path(status["final_video"]).name == "final_video.mp4"
    assert Path(status["final_video"]).exists()

    result = client.get(f"/api/projects/{pid}/result").json()
    assert result["final_video"] == status["final_video"]


def test_cancel_waiting_job_leaves_queue_empty(api, monkeypatch: pytest.MonkeyPatch):
    client, store, _ = api
    pid = client.post("/api/projects", json={"brief": "x", "language": "zh"}).json()[
        "project_id"
    ]
    client.post(
        f"/api/projects/{pid}/upload",
        files={"file": ("walk.mp4", b"data", "video/mp4")},
    )
    from backend.api import jobs as jobs_api

    monkeypatch.setattr(jobs_api, "start_job_task", lambda job: None)
    job_id = client.post("/api/jobs", json={"project_id": pid}).json()["job_id"]
    assert store.get_job(job_id).status == "waiting"

    cancelled = client.post(f"/api/projects/{pid}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert store.get_job(job_id).status == "cancelled"
    assert client.get("/api/jobs/next").json() is None

    revived = client.post(
        "/api/jobs/update",
        json={"job_id": job_id, "stage": "Vision Analysis", "progress": 15, "status": "running"},
    )
    assert revived.json()["status"] == "cancelled"


def test_produce_alias_enqueues_job(api, monkeypatch: pytest.MonkeyPatch):
    client, store, _ = api
    pid = client.post("/api/projects", json={"brief": "x", "language": "en"}).json()[
        "project_id"
    ]
    client.post(
        f"/api/projects/{pid}/upload",
        files={"file": ("walk.mov", b"data", "video/quicktime")},
    )

    from backend.api import jobs as jobs_api

    monkeypatch.setattr(jobs_api, "start_job_task", lambda job: None)

    res = client.post(f"/api/projects/{pid}/produce")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    assert store.get_job(body["job_id"]).status == "waiting"
