#!/usr/bin/env bash
# Robustness suite: our own hidden-like scenarios (scripts/make_robustness_scenarios.py), one Linux container
# each (2 vCPU), in parallel. Results: runs/robustness/<name>.{md,json,db,ctl.log} and reports/robustness.md
set -euo pipefail
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
PY="${OUTCOMELOOP_PYTHON:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || ( [[ -x .venv/Scripts/python.exe ]] && echo .venv/Scripts/python.exe || echo python3 ) )}"
"$PY" scripts/make_robustness_scenarios.py
docker build -q -t outcomeloop . > /dev/null
OUTDIR="$(pwd)/runs/robustness"; rm -rf "$OUTDIR"; mkdir -p "$OUTDIR"
for f in tests/robustness/*.yaml ${EXTRA_SCENARIOS:-}; do
  n=$(basename "$f" .yaml)
  docker run --rm --cpus 2 --memory 4g -v "$OUTDIR:/out" outcomeloop scripts/docker_scenario.sh "$f" /out > "$OUTDIR/$n.out" 2>&1 &
done
wait
"$PY" scripts/robustness_summary.py runs/robustness reports/robustness.md
