#!/usr/bin/env bash
# OutcomeLoop controller. Contract: ./run.sh <SIM_URL> runs until the scenario finishes, no manual steps.
#
# Runs natively with Python 3.11+ (no Docker needed). Dependencies are the ones already in requirements.txt
# (httpx, numpy); storage is an embedded SQLite file, so there is no service to start.
#
#   OUTCOMELOOP_DB      path of the durable state (default: state/outcomeloop.db). Keep it across restarts:
#                       re-running against the same simulator resumes (crash recovery). A different
#                       simulator world is detected and the old DB is archived automatically.
#   OUTCOMELOOP_LOG     log level (default INFO)
#   OUTCOMELOOP_PYTHON  interpreter to use (default: .venv if present, else python3)
set -euo pipefail
export PYTHONUTF8=1
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd "$(dirname "$0")"

PY="${OUTCOMELOOP_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python
  elif [[ -x .venv/Scripts/python.exe ]]; then PY=.venv/Scripts/python.exe
  else PY=python3; fi
fi
if ! "$PY" -c "import httpx, numpy" 2>/dev/null; then
  echo "installing dependencies into $PY" >&2
  "$PY" -m pip install -q -r requirements.txt
fi

# native path for the interpreter (Git Bash on Windows: `pwd -W`; Linux/macOS: plain pwd)
SRC="$(cd src && (pwd -W 2>/dev/null || pwd))"
case "$SRC" in [A-Za-z]:*) SEP=";" ;; *) SEP=":" ;; esac
export PYTHONPATH="$SRC${PYTHONPATH:+$SEP$PYTHONPATH}"

# Tiny supervisor: the controller is crash-safe (durable state + reconciliation on start), so if it ever dies
# unexpectedly we restart it against the same DB and it resumes. It exits 0 only when the scenario finished.
MAX_RESTARTS="${OUTCOMELOOP_MAX_RESTARTS:-20}"
for attempt in $(seq 0 "$MAX_RESTARTS"); do
  rc=0
  "$PY" -m outcomeloop run --url "$SIM_URL" || rc=$?
  if [[ $rc -eq 0 ]]; then
    exit 0
  fi
  echo "[run.sh] controller exited with status $rc (attempt $attempt); restarting from durable state in 5s" >&2
  sleep 5
done
echo "[run.sh] giving up after $MAX_RESTARTS restarts" >&2
exit 1
