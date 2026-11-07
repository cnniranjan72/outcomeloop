# Measured scaling: 1× vs 3× public_03

Generated with `scripts/make_scale_scenario.py` (K copies of every public_03 workflow under new ids, 2 simulated days,
3 days of history), run in a Linux container capped at the grader's spec (`--cpus 4 --memory 8g`,
`scripts/docker_scenario.sh`), one after the other, same code (commit `333ab02`+: hourly rollups, person-time on).
Numbers are read from each run's own `metrics` / `chunks` tables. The host also ran unrelated containers, so absolute
times are conservative; the ratio between the two runs is the point.

| | 1× (12 workflows) | 3× (36 workflows) | ratio |
|---|---|---|---|
| events per simulated day | 840,055 / 840,039 | 2,520,163 / 2,520,125 | 3.0× |
| ingest seconds per simulated day | 24.5 / 29.3 | 72.0 / 71.5 | 2.6× |
| decide seconds per simulated day | 18.6 / 21.5 | 54.0 / 53.2 | 2.6× |
| **controller seconds per simulated day** | **43.1 / 50.8** | **126.0 / 124.7** | **2.7×** |
| simulator seconds per simulated day (not ours) | 16.6 / 20.3 | 45.4 / 46.9 | 2.6× |
| history ingest throughput | 35,467 events/s | 40,793 events/s | |
| live ingest throughput | 39,459 events/s | 42,251 events/s | |
| per-tick controller time p95 / max | 1.24 s / 7.2 s | 3.42 s / 22.3 s | |
| peak memory (ru_maxrss) | 898 MB | 1,036 MB | 1.15× |
| SQLite file at end | 185 MB | 559 MB | 3.0× |
| decision errors | 0 | 0 | |
| run.sh wall-clock (incl. waiting on the simulator) | 201 s | 521 s | |

Reading it:

* Controller cost grows **linearly (slightly sub-linearly)** with load: ingest and decisions both ~2.6× for 3×
  the events and workflows. Memory barely grows — analysis is SQL over an on-disk store and hourly rollups, not
  in-memory state.
* Linear extrapolation to 10× public_03 (≈ 8.4 M events/day, 120 workflows) gives **≈ 420 s of controller time
  per simulated day** on 4 vCPU — under the 600 s target, but without much headroom. The limit is the single
  process (one SQLite writer, decisions serial across workflows), which is what SUBMISSION §8 names as the first
  thing to change: shard workflows across processes (hash of `workflow_id`), each with its own checkpoint.
* This is a 2-point curve on generated copies of the public workload, not a production load test.
