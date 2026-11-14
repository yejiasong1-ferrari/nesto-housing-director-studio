from __future__ import annotations

import requests

import api_client
from backend.progress import JobCancelled


def test_cancel_check_timeout_is_soft(monkeypatch) -> None:
    def raise_timeout(_job_id: str) -> dict:
        raise requests.Timeout("slow backend")

    monkeypatch.setattr(api_client, "fetch_job", raise_timeout)

    api_client.raise_if_cancelled("job_timeout")


def test_cancel_check_still_stops_cancelled_job() -> None:
    try:
        api_client.raise_if_cancelled("job_cancelled", {"status": "cancelled"})
    except JobCancelled:
        return
    raise AssertionError("cancelled job should raise JobCancelled")
