"""Phantom-claim recovery: running/Claimed jobs that the Worker never started."""

from datetime import datetime, timedelta, timezone

from backend.database import should_requeue_running_job


NOW = datetime(2026, 8, 23, 7, 20, tzinfo=timezone.utc)


def test_requeue_recent_claimed_job_after_timeout():
    assert should_requeue_running_job(
        status="running",
        stage="Claimed",
        progress=1,
        updated_at=NOW - timedelta(seconds=91),
        created_at=NOW - timedelta(minutes=15),
        now=NOW,
    )


def test_keep_fresh_claim_so_worker_can_start():
    assert not should_requeue_running_job(
        status="running",
        stage="Claimed",
        progress=1,
        updated_at=NOW - timedelta(seconds=20),
        created_at=NOW - timedelta(seconds=30),
        now=NOW,
    )


def test_keep_mid_pipeline_and_old_orphans():
    assert not should_requeue_running_job(
        status="running",
        stage="Script & Voice",
        progress=40,
        updated_at=NOW - timedelta(hours=19),
        created_at=NOW - timedelta(hours=19),
        now=NOW,
    )
    assert not should_requeue_running_job(
        status="running",
        stage="Claimed",
        progress=1,
        updated_at=NOW - timedelta(days=30),
        created_at=NOW - timedelta(days=39),
        now=NOW,
    )
    assert not should_requeue_running_job(
        status="waiting",
        stage="Queued",
        progress=0,
        updated_at=NOW - timedelta(minutes=10),
        created_at=NOW - timedelta(minutes=10),
        now=NOW,
    )
