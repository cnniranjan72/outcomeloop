#!/usr/bin/env bash
# Measured scaling curve: 1x and 3x public_03 (2 simulated days each) in a Linux container at the grader's spec,
# one after the other, then reports/scaling.md from the runs' own metrics.
#   scripts/scaling.sh            (needs docker)
set -euo pipefail
export PYTHONUTF8=1
cd "$(dirname "$0")/.."
PY="${OUTCOMELOOP_PYTHON:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || echo .venv/Scripts/python.exe )}"
"$PY" scripts/make_scale_scenario.py 1 2
"$PY" scripts/make_scale_scenario.py 3 2
docker build -q -t outcomeloop . >/dev/null
OUT="$(pwd)/runs/scaling"; rm -rf "$OUT"; mkdir -p "$OUT"
for k in 1 3; do
  MSYS_NO_PATHCONV=1 docker run --rm --cpus 4 --memory 8g -v "$OUT:/out" -v "$(pwd)/tests/scale:/scale:ro" outcomeloop \
    bash -c "scripts/docker_scenario.sh /scale/load_x${k}_d2.yaml /out" | tail -3
done
"$PY" scripts/scale_report.py "$OUT/load_x1_d2.db" "$OUT/load_x3_d2.db" --out reports/scaling.md
