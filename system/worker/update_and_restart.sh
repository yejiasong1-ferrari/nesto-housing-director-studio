#!/usr/bin/env bash
# Update Mac Worker to latest main and restart the poll loop.
# Run from anywhere:
#   bash system/worker/update_and_restart.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> git pull"
git pull origin main

echo "==> verify Verified Space Layer on disk"
PYTHONPATH=system python3 - <<'PY'
from backend.agents.vision.modules.space_evidence_validator import validate_verified_vkb
from backend.agents.script.pipeline.marketing_enricher import ensure_required_space_coverage
from backend.agents.script.speaking_rate import EN_WORDS_PER_SECOND, ZH_CHARS_PER_SECOND
print("OK:", validate_verified_vkb.__name__, ensure_required_space_coverage.__name__,
      f"en={EN_WORDS_PER_SECOND}wps zh={ZH_CHARS_PER_SECOND}cps")
PY

echo "==> restart worker"
pkill -f "system/worker/worker.py" 2>/dev/null || true
sleep 1

export PYTHONUNBUFFERED=1
export PYTHONPATH=system:system/worker
# Prefer CommandLineTools python (matches prior local Worker runs), else python3
PYBIN="${WORKER_PYTHON:-}"
if [[ -z "$PYBIN" ]]; then
  if [[ -x /Library/Developer/CommandLineTools/usr/bin/python3 ]]; then
    PYBIN=/Library/Developer/CommandLineTools/usr/bin/python3
  else
    PYBIN=python3
  fi
fi

nohup "$PYBIN" system/worker/worker.py >> system/worker/worker.log 2>&1 &
echo "Worker PID $!  (logs: system/worker/worker.log)"
sleep 2
tail -n 8 system/worker/worker.log || true
echo "Done. Queue a create job (not Studio export-only) to re-run Vision."
