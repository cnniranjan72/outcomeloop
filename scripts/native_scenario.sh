#!/usr/bin/env bash
# Native (no Docker) twin of docker_scenario.sh: baseline -> simulator on PORT -> ./run.sh -> grade into OUT.
#   scripts/native_scenario.sh <scenario.yaml> <port> <outdir>
set -euo pipefail
export PYTHONUTF8=1
cd "$(dirname "$0")/.."
SCEN="$1"; PORT="$2"; OUT="$3"; NAME="$(basename "$SCEN" .yaml)"
PY="${OUTCOMELOOP_PYTHON:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || ( [[ -x .venv/Scripts/python.exe ]] && echo .venv/Scripts/python.exe || echo python3 ) )}"
RD="runs/native/$NAME"; rm -rf "$RD"; mkdir -p "$RD" "$OUT"
"$PY" -m sim baseline --scenario "$SCEN" --run-dir "$RD/base" | tail -1
"$PY" -m sim serve --scenario "$SCEN" --run-dir "$RD/mine" --port "$PORT" > "$RD/sim.log" 2>&1 &
SIM=$!; trap 'kill $SIM 2>/dev/null || true' EXIT
until curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; do kill -0 $SIM || exit 1; sleep 2; done
export OUTCOMELOOP_DB="$RD/ctl.db"
START=$(date +%s)
set +e; ./run.sh "http://127.0.0.1:$PORT" > "$RD/ctl.log" 2>&1; RC=$?; set -e
echo "run.sh exit=$RC in $(( $(date +%s) - START ))s"
"$PY" -m sim grade --run "$RD/mine" --baseline "$RD/base" --out "$OUT/$NAME.md" > /dev/null
"$PY" -m sim grade --run "$RD/mine" --baseline "$RD/base" --json > "$OUT/$NAME.json"
cp "$RD/ctl.log" "$OUT/$NAME.ctl.log"; cp "$RD/ctl.db" "$OUT/$NAME.db" 2>/dev/null || true
