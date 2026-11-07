#!/usr/bin/env bash
# Robustness suite: our own hidden-like scenarios (scripts/make_robustness_scenarios.py), one Linux container
# each (2 vCPU / 2 GB), up to MAX_PARALLEL (8) at a time. SEED_REPLICAS=2 adds a second seed of every scenario. Results: runs/robustness/<name>.{md,json,db,ctl.log} and reports/robustness.md
set -euo pipefail
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
PY="${OUTCOMELOOP_PYTHON:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || ( [[ -x .venv/Scripts/python.exe ]] && echo .venv/Scripts/python.exe || echo python3 ) )}"
"$PY" scripts/make_robustness_scenarios.py
MODE=docker
if ! docker info >/dev/null 2>&1; then MODE=native; unset MSYS_NO_PATHCONV; echo "docker not available: running natively"; fi
[[ $MODE == docker ]] && docker build -q -t outcomeloop . > /dev/null
OUTREL="${ROBUST_OUT:-runs/robustness}"; OUTDIR="$(pwd)/$OUTREL"; rm -rf "$OUTDIR"; mkdir -p "$OUTDIR"
ENVARGS=(); [[ -n "${OUTCOMELOOP_PERSON_TIME:-}" ]] && ENVARGS=(-e "OUTCOMELOOP_PERSON_TIME=$OUTCOMELOOP_PERSON_TIME")
MAXJ="${MAX_PARALLEL:-8}"
for f in tests/robustness/*.yaml ${EXTRA_SCENARIOS:-}; do
  n=$(basename "$f" .yaml)
  while (( $(jobs -rp | wc -l) >= MAXJ )); do wait -n || true; done
  i=$(( ${i:-0} + 1 ))
  if [[ $MODE == docker ]]; then
    docker run --rm --cpus 2 --memory 2g "${ENVARGS[@]}" -v "$OUTDIR:/out" outcomeloop scripts/docker_scenario.sh "$f" /out > "$OUTDIR/$n.out" 2>&1 &
  else
    scripts/native_scenario.sh "$f" $((8750 + i)) "$OUTREL" > "$OUTDIR/$n.out" 2>&1 &
  fi
done
wait || true
"$PY" scripts/robustness_summary.py "$OUTREL" "${ROBUST_REPORT:-reports/robustness.md}"
