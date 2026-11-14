"""Nesto GPU Worker — poll Backend, run AI Director, upload to R2.

Run from repo root (recommended)::

    PYTHONPATH=system:system/worker python system/worker/worker.py

Or from ``system/worker``::

    PYTHONPATH=..:..:. python worker.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# Ensure ``system/`` and this package dir are importable when run as a script.
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

from api_client import JobCancelled, get_job  # noqa: E402
from processor import process  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("nesto.worker")

POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "5"))


def main() -> None:
    backend = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
    print("AI Worker started")
    print(f"  Backend: {backend}")
    print(f"  Poll every {POLL_SECONDS:g}s")
    logger.info("Listening for jobs…")
    fail_streak = 0

    while True:
        try:
            job = get_job()
            fail_streak = 0
        except Exception as exc:  # noqa: BLE001
            fail_streak += 1
            wait = min(12.0, POLL_SECONDS * (2 ** min(fail_streak, 2)))
            logger.warning("Poll failed (%s): %s — retry in %.0fs", fail_streak, exc, wait)
            time.sleep(wait)
            continue

        if job:
            job_id = job.get("id") or job.get("job_id")
            print(f"Found job: {job_id}")
            try:
                process(job)
                print(f"Completed: {job_id}")
            except JobCancelled:
                print(f"Cancelled: {job_id} — worker free for the next job")
            except Exception as exc:  # noqa: BLE001
                print(f"Failed: {job_id} — {exc}")
        else:
            print("No jobs")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
