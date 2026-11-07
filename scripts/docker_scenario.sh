#!/usr/bin/env bash
# Inside the container: baseline -> simulator -> ./run.sh -> grade, exactly as the assignment README describes.
#   scripts/docker_scenario.sh public_01_dev            (a public scenario name)
#   scripts/docker_scenario.sh tests/robustness/r3_null_effects.yaml /out   (a path, results copied to /out)
set -euo pipefail
ARG="${1:-public_01_dev}"; OUT="${2:-reports}"
if [[ -f "$ARG" ]]; then SCEN="$ARG"; NAME="$(basename "$ARG" .yaml)"; else SCEN="scenarios/${ARG}.yaml"; NAME="$ARG"; fi
mkdir -p runs "$OUT"
python -m sim baseline --scenario "$SCEN" --run-dir "runs/base_${NAME}" | tail -1
python -m sim serve --scenario "$SCEN" --run-dir "runs/mine_${NAME}" --port 8700 > runs/sim.log 2>&1 &
until curl -sf http://127.0.0.1:8700/health >/dev/null; do sleep 2; done
START=$(date +%s)
set +e; ./run.sh http://127.0.0.1:8700 > "runs/ctl.log" 2>&1; RC=$?; set -e
echo "run.sh exit=$RC in $(( $(date +%s) - START ))s"
python -m sim grade --run "runs/mine_${NAME}" --baseline "runs/base_${NAME}" --out "$OUT/${NAME}.md" > /dev/null
python -m sim grade --run "runs/mine_${NAME}" --baseline "runs/base_${NAME}" --json > "$OUT/${NAME}.json"
cp runs/ctl.log "$OUT/${NAME}.ctl.log"; cp "${OUTCOMELOOP_DB:-state/outcomeloop.db}" "$OUT/${NAME}.db" 2>/dev/null || true
sed -n '5,12p;/applied —/p' "$OUT/${NAME}.md"
