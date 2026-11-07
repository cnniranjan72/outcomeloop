#!/usr/bin/env bash
# Run one scenario end to end: baseline (if missing) → simulator → ./run.sh → grade.
#   scripts/run_scenario.sh public_01_dev [port]
# Outputs: runs/mine_<name>/ (sim run dir), runs/ctl_<name>.log, reports/<name>.md, state/<name>.db
set -euo pipefail
export PYTHONUTF8=1
cd "$(dirname "$0")/.."
NAME="${1:?usage: scripts/run_scenario.sh <scenario-name> [port]}"
PORT="${2:-8700}"
SCEN="scenarios/${NAME}.yaml"
PY="${OUTCOMELOOP_PYTHON:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || ( [[ -x .venv/Scripts/python.exe ]] && echo .venv/Scripts/python.exe || echo python3 ) )}"
mkdir -p runs reports state

if [[ ! -f "runs/base_${NAME}/_truth/aggregates.json" ]]; then
  echo "[run_scenario] baseline for $NAME"
  "$PY" -m sim baseline --scenario "$SCEN" --run-dir "runs/base_${NAME}"
fi

echo "[run_scenario] starting simulator on :$PORT"
"$PY" -m sim serve --scenario "$SCEN" --run-dir "runs/mine_${NAME}" --port "$PORT" --force > "runs/sim_${NAME}.log" 2>&1 &
SIM_PID=$!
trap 'kill $SIM_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 900); do
  curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 && break
  kill -0 $SIM_PID 2>/dev/null || { echo "simulator died"; cat "runs/sim_${NAME}.log"; exit 1; }
  sleep 1
done

export OUTCOMELOOP_DB="state/${NAME}.db"
rm -f "$OUTCOMELOOP_DB" "$OUTCOMELOOP_DB-wal" "$OUTCOMELOOP_DB-shm"
START=$(date +%s)
./run.sh "http://127.0.0.1:${PORT}" > "runs/ctl_${NAME}.log" 2>&1
echo "[run_scenario] controller finished in $(( $(date +%s) - START ))s"

"$PY" -m sim grade --run "runs/mine_${NAME}" --baseline "runs/base_${NAME}" --out "reports/${NAME}.md" > /dev/null
echo "[run_scenario] report: reports/${NAME}.md"
head -12 "reports/${NAME}.md"
