"""Phase 4 upload-url / upload-complete unit tests (R2 mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.database import InMemoryDB
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
    ):
        monkeypatch.setattr(target, store)

    monkeypatch.setattr("backend.r2.r2_configured", lambda: True)
    monkeypatch.setattr("backend.r2.R2_BUCKET", "nesto-director")

    with TestClient(app) as client:
        yield client, store


def test_upload_url_and_complete(api, monkeypatch: pytest.MonkeyPatch):
    client, store = api
    pid = client.post(
        "/api/projects",
        json={"brief": "kitchen", "language": "en", "email": "r2@example.com"},
    ).json()["project_id"]

    monkeypatch.setattr(
        "backend.r2.generate_upload_url",
        lambda key, content_type="video/mp4", expires_in=3600: f"https://r2.example/put/{key}",
    )
    monkeypatch.setattr("backend.r2.object_exists", lambda key: True)
    monkeypatch.setattr(
        "backend.r2.r2_public_uri",
        lambda key: f"r2://nesto-director/{key}",
    )

    url_res = client.post(
        "/api/upload-url",
        json={"filename": "house.mov", "project_id": pid, "content_type": "video/quicktime"},
    )
    assert url_res.status_code == 200, url_res.text
    body = url_res.json()
    assert body["upload_url"].startswith("https://")
    assert pid in body["key"]
    assert "users/" in body["key"]

    done = client.post(
        "/api/upload-complete",
        json={"project_id": pid, "key": body["key"], "create_job": True, "verify_object": True},
    )
    assert done.status_code == 200, done.text
    payload = done.json()
    assert payload["status"] == "queued"
    assert payload["job_id"]
    assert payload["video_url"].startswith("r2://")

    job = store.get_job(payload["job_id"])
    assert job is not None
    assert job.status == "waiting"
    project = store.get_project(pid)
    assert project.video_url == payload["video_url"]
