#!/usr/bin/env bash
# Load test on public_03_load (12 workflows, ~650k dials/day). Produces reports/public_03.md from measured values.
#   scripts/load_test.sh [port]
set -euo pipefail
export PYTHONUTF8=1
cd "$(dirname "$0")/.."
PORT="${1:-8703}"
PY="${OUTCOMELOOP_PYTHON:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || ( [[ -x .venv/Scripts/python.exe ]] && echo .venv/Scripts/python.exe || echo python3 ) )}"
scripts/run_scenario.sh public_03_load "$PORT"
WALL=$(cat runs/ctl_public_03_load.secs)
cp reports/public_03_load.md reports/public_03_grade.md
"$PY" scripts/load_report.py --db state/public_03_load.db --grade reports/public_03_grade.md --wall "$WALL" \
  --out reports/public_03.md --note "${LOAD_NOTE:-}"
