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

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m outcomeloop run --url "$SIM_URL"
