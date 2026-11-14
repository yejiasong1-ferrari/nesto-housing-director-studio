"""Admin console API — separate from History beta_account scoping."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.invite_db import invite_db, verify_and_activate
from backend.main import app
from backend.database import db
from backend.models import Project


client = TestClient(app)


def test_admin_lists_all_projects_without_touching_history_scope():
    inv = invite_db.create_code("NESTO-ADMINTEST1")
    sess_a, _, acc_a = verify_and_activate(inv.code, device_id="dev_a")
    inv2 = invite_db.create_code("NESTO-ADMINTEST2")
    sess_b, _, acc_b = verify_and_activate(inv2.code, device_id="dev_b")

    p1 = Project(
        project_id=db.new_id("proj_"),
        beta_account_id=acc_a.id,
        title="A Home",
        status="completed",
        final_video="r2://nesto-director/users/a/final.mp4",
    )
    p2 = Project(
        project_id=db.new_id("proj_"),
        beta_account_id=acc_b.id,
        title="B Home",
        status="created",
    )
    db.create_project(p1)
    db.create_project(p2)

    # User History stays scoped
    hist_a = client.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {sess_a.token}"},
    )
    assert hist_a.status_code == 200
    ids_a = {p["project_id"] for p in hist_a.json()}
    assert p1.project_id in ids_a
    assert p2.project_id not in ids_a

    # Admin sees both (memory mode allows empty admin key)
    admin = client.get("/api/admin/projects")
    assert admin.status_code == 200
    admin_ids = {p["project_id"] for p in admin.json()["projects"]}
    assert p1.project_id in admin_ids
    assert p2.project_id in admin_ids


def test_view_as_is_read_only():
    inv = invite_db.create_code("NESTO-VIEWAS01")
    _, _, acc = verify_and_activate(inv.code, device_id="dev_view")
    view = client.post(f"/api/admin/users/{acc.id}/view-as", json={"ttl_hours": 1})
    assert view.status_code == 200
    token = view.json()["token"]
    assert view.json()["read_only"] is True

    # Read History OK
    hist = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert hist.status_code == 200

    # Write blocked
    create = client.post(
        "/api/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"brief": "x", "language": "zh"},
    )
    assert create.status_code == 403


def test_force_logout_cancels_jobs():
    from backend.models import Job

    inv = invite_db.create_code("NESTO-FORCE01")
    sess, _, acc = verify_and_activate(inv.code, device_id="dev_force")
    proj = Project(
        project_id=db.new_id("proj_"),
        beta_account_id=acc.id,
        title="Force Home",
        status="processing",
    )
    db.create_project(proj)
    job = Job(
        job_id=db.new_id("job_"),
        project_id=proj.project_id,
        status="running",
        stage="Vision",
        progress=40,
    )
    db.create_job(job)
    proj.active_job_id = job.job_id
    db.save_project(proj)

    rev = client.post(f"/api/admin/users/{acc.id}/force-logout")
    assert rev.status_code == 200
    body = rev.json()
    assert body["status"] == "revoked"
    assert body["jobs_cancelled"] == 1
    assert db.get_job(job.job_id).status == "cancelled"

    hb = client.post(
        "/api/session/heartbeat",
        headers={"Authorization": f"Bearer {sess.token}"},
        json={"current_page": "studio"},
    )
    assert hb.status_code == 401
    assert hb.json()["detail"]["code"] == "account_revoked"


def test_revoke_invite_does_not_cancel_jobs():
    from backend.models import Job

    inv = invite_db.create_code("NESTO-INVREV01")
    _, _, acc = verify_and_activate(inv.code, device_id="dev_invrev")
    proj = Project(
        project_id=db.new_id("proj_"),
        beta_account_id=acc.id,
        title="Keep Running",
        status="processing",
    )
    db.create_project(proj)
    job = Job(
        job_id=db.new_id("job_"),
        project_id=proj.project_id,
        status="running",
        stage="Script",
        progress=20,
    )
    db.create_job(job)

    rev = client.post(f"/api/admin/invites/{inv.code}/revoke")
    assert rev.status_code == 200
    assert rev.json()["status"] == "expired"
    assert db.get_job(job.job_id).status == "running"
    assert invite_db.get_account(acc.id).status == "revoked"


def test_revoke_forces_logout():
    inv = invite_db.create_code("NESTO-REVOKE01")
    sess, _, acc = verify_and_activate(inv.code, device_id="dev_rev")
    ok = client.get(
        "/api/invite/session",
        headers={"Authorization": f"Bearer {sess.token}"},
    )
    assert ok.json()["valid"] is True

    rev = client.post(f"/api/admin/users/{acc.id}/revoke")
    assert rev.status_code == 200
    assert rev.json()["status"] == "revoked"

    # Heartbeat / protected routes should report account_revoked
    hb = client.post(
        "/api/session/heartbeat",
        headers={"Authorization": f"Bearer {sess.token}"},
        json={"current_page": "studio"},
    )
    assert hb.status_code == 401
    detail = hb.json()["detail"]
    assert detail["code"] == "account_revoked"

    dead = client.get(
        "/api/invite/session",
        headers={"Authorization": f"Bearer {sess.token}"},
    )
    assert dead.status_code == 401
    assert dead.json()["detail"]["code"] == "account_revoked"
