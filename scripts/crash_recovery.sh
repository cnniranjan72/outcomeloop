#!/usr/bin/env bash
# Crash-recovery evidence: start the simulator, hard-kill the controller at 7 chosen moments (SIGKILL /
# TerminateProcess), restart it each time, let it finish, then verify exactly-once ingestion, no double apply,
# no lost approvals, learning kept, run finished, and grade it.
#   scripts/crash_recovery.sh                 # public_02_incidents on :8711
#   scripts/crash_recovery.sh --port 8712     # any extra args go to scripts/crash_recovery.py
# Outputs: reports/crash_recovery_timeline.json, reports/crash_public_02_grade.md,
#          runs/crash_public_02/ (sim run dir), runs/crash_public_02_ctl.log, state/crash_public_02.db
set -euo pipefail
export PYTHONUTF8=1
cd "$(dirname "$0")/.."
PY="${OUTCOMELOOP_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python
  elif [[ -x .venv/Scripts/python.exe ]]; then PY=.venv/Scripts/python.exe
  else PY=python3; fi
fi
exec "$PY" scripts/crash_recovery.py "$@"
