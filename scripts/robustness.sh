#!/usr/bin/env bash
# Robustness suite: our own hidden-like scenarios (scripts/make_robustness_scenarios.py), one Linux container
# each (2 vCPU / 2 GB), up to MAX_PARALLEL (8) at a time. SEED_REPLICAS=2 adds a second seed of every scenario. Results: runs/robustness/<name>.{md,json,db,ctl.log} and reports/robustness.md
set -euo pipefail
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
PY="${OUTCOMELOOP_PYTHON:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || ( [[ -x .venv/Scripts/python.exe ]] && echo .venv/Scripts/python.exe || echo python3 ) )}"
"$PY" scripts/make_robustness_scenarios.py
docker build -q -t outcomeloop . > /dev/null
OUTDIR="$(pwd)/runs/robustness"; rm -rf "$OUTDIR"; mkdir -p "$OUTDIR"
MAXJ="${MAX_PARALLEL:-8}"
for f in tests/robustness/*.yaml ${EXTRA_SCENARIOS:-}; do
  n=$(basename "$f" .yaml)
  while (( $(jobs -rp | wc -l) >= MAXJ )); do wait -n; done
  docker run --rm --cpus 2 --memory 2g -v "$OUTDIR:/out" outcomeloop scripts/docker_scenario.sh "$f" /out > "$OUTDIR/$n.out" 2>&1 &
done
wait
"$PY" scripts/robustness_summary.py runs/robustness reports/robustness.md
