#!/usr/bin/env bash
# Graceful-stop evidence (Linux / Docker): SIGTERM to run.sh mid-run -> controller stops between steps and records
# controller_stop -> restart on the same DB -> scenario finishes. Run inside the container:
#   docker run --rm outcomeloop scripts/graceful_stop_test.sh
set -euo pipefail
export OUTCOMELOOP_DB=state/graceful.db PYTHONUTF8=1
rm -f state/graceful.db*
python -m sim serve --scenario scenarios/public_01_dev.yaml --run-dir runs/graceful --port 8700 --force > /tmp/sim.log 2>&1 &
SIM=$!
trap 'kill $SIM 2>/dev/null || true' EXIT
until curl -sf http://127.0.0.1:8700/health >/dev/null; do kill -0 $SIM 2>/dev/null || { cat /tmp/sim.log; exit 1; }; sleep 1; done
./run.sh http://127.0.0.1:8700 > /tmp/ctl1.log 2>&1 &
RUN=$!
sleep 25
echo "sim minute at SIGTERM: $(curl -s http://127.0.0.1:8700/sim/state | python -c 'import json,sys; print(json.load(sys.stdin)["sim_minute"])')"
kill -TERM "$RUN"; set +e; wait "$RUN"; echo "run.sh exit after SIGTERM: $?"; set -e
grep -E "signal|stopped gracefully" /tmp/ctl1.log | tail -2
python - <<'PY'
import sqlite3; c = sqlite3.connect("state/graceful.db")
print("decisions at stop:", c.execute("select count(*) from decisions").fetchone()[0],
      "| controller_stop rows:", c.execute("select count(*) from decisions where kind='controller_stop'").fetchone()[0],
      "| proposals in uncertain states:", c.execute("select count(*) from proposals where state in ('SUBMITTING','APPLYING','AUTO_APPLYING')").fetchone()[0])
PY
./run.sh http://127.0.0.1:8700 > /tmp/ctl2.log 2>&1; echo "restart exit: $?"
python - <<'PY'
import sqlite3, json, urllib.request
c = sqlite3.connect("state/graceful.db")
st = json.load(urllib.request.urlopen("http://127.0.0.1:8700/sim/state"))
ours = c.execute("select sum(events) from chunks").fetchone()[0]
print("finished:", st["finished"], "| events ingested == simulator last_event_id:", ours == st["last_event_id"], ours,
      "| restart decisions:", c.execute("select count(*) from decisions where kind='controller_restart'").fetchone()[0],
      "| finish decisions:", c.execute("select count(*) from decisions where kind='controller_finish'").fetchone()[0])
PY
