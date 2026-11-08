#!/usr/bin/env bash
# Is the controller deterministic? Run one scenario twice against identically seeded simulators, with the
# controller's Python hash seed different each time, and compare every decision and every simulator event.
#   scripts/determinism_check.sh [scenario] [port]
# Any difference means controller behaviour depends on something other than its inputs (e.g. set iteration order).
set -uo pipefail
export PYTHONUTF8=1
cd "$(dirname "$0")/.."
SCEN="${1:-public_02_incidents}"; PORT="${2:-8790}"
PY="${OUTCOMELOOP_PYTHON:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || echo .venv/Scripts/python.exe )}"
W=runs/determinism; mkdir -p "$W"
for i in 1 2; do
  rm -rf "$W/run$i" "$W/run$i.db" "$W/run$i.db-wal" "$W/run$i.db-shm"
  PYTHONHASHSEED=0 "$PY" -m sim serve --scenario "scenarios/$SCEN.yaml" --run-dir "$W/run$i" --port $((PORT + i)) \
    > "$W/sim$i.log" 2>&1 &
  SIM=$!
  for _ in $(seq 60); do curl -sf "http://127.0.0.1:$((PORT + i))/health" >/dev/null && break; sleep 1; done
  PYTHONHASHSEED=$((i * 7919)) OUTCOMELOOP_DB="$W/run$i.db" ./run.sh "http://127.0.0.1:$((PORT + i))" \
    > "$W/ctl$i.log" 2>&1
  echo "run $i: run.sh exit $? (controller hash seed $((i * 7919)))"
  kill $SIM 2>/dev/null; wait $SIM 2>/dev/null
done
"$PY" - "$W" <<'EOF'
import sqlite3, sys, filecmp, os
w = sys.argv[1]
q = ("SELECT minute, wf, kind, summary FROM decisions WHERE kind NOT IN ('controller_start','controller_finish',"
     "'controller_restart') ORDER BY decision_id")
a = list(sqlite3.connect(f"{w}/run1.db").execute(q))
b = list(sqlite3.connect(f"{w}/run2.db").execute(q))
ev = sorted(os.listdir(f"{w}/run1/events"))
diff_ev = next((f for f in ev if not filecmp.cmp(f"{w}/run1/events/{f}", f"{w}/run2/events/{f}", shallow=False)), None)
print(f"decisions: {len(a)} vs {len(b)} -> {'IDENTICAL' if a == b else 'DIFFERENT'}")
print(f"simulator event chunks: {len(ev)} -> {'IDENTICAL' if diff_ev is None else 'first difference in ' + diff_ev}")
sys.exit(0 if a == b and diff_ev is None else 1)
EOF
