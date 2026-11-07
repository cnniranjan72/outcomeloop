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

## Where the time goes (measured on the final code) and what changes first at 10×

**Ingest is CPU-bound in one Python process.** `scripts/bench_ingest.py --phases` ingests the first 8 public_03
history chunks (2,000,000 events) from a running simulator into a fresh store and attributes the time
(12-CPU Windows laptop, simulator on the same host, two runs):

| phase | share of ingest time |
|---|---|
| bulk inserts (`executemany` into calls / leads / persons) | 19 % |
| hourly rollups (recomputed per touched workflow-hour) | 7–8 % |
| commits (`synchronous=FULL`) | 4 % |
| reading + JSON-parsing the chunk, and the per-event Python transform | 70 % |

Reading and parsing alone is 1.4–4.4 s per 250k-event chunk (measured separately), so roughly half the ingest time
is the per-event Python transform (~17 µs/event): one core, saturated. cProfile on two simulated days agrees on the
shape (JSON decode, socket reads, then `db.code`, id parsing and feature lookups). SQLite itself is under a third.

**Decisions** are about 40 % of controller time and grow with the number of workflows (serial, one workflow at a
time). The largest single item in the profile was deep-copying a ~200 KB config several times per workflow-hour.

**What we changed, and what it bought (honestly small):**
- per-chunk memo of the string→code lookups (34 M `db.code()` calls on public_03): +1.6 % on the ingest benchmark,
  inside run-to-run noise. Kept because it is correct, tested and removes work; not claimed as a speed-up.
- config copies by JSON round-trip instead of `copy.deepcopy`: 3.3 ms vs 5.1 ms per copy on a real config
  (identical result), ≈ 1 s per simulated day at 1×.
- the memory fix (`reports/memory.md`) also made history ingest faster in the full load test.

**What fails first at 10×, in order:**
1. *Ingest CPU on one core.* ~10× the events means ~10× the per-event Python work; a single process cannot use the
   other cores. Fix: shard workflows across processes by hash of `workflow_id` (each with its own store and
   checkpoint; the simulator's chunk stream is read once and fanned out, or each shard filters by workflow).
   Workflows are independent except for the shared credit budget, which becomes a small shared ledger.
2. *Decisions serial across workflows.* Same sharding parallelises them.
3. *SQLite single writer.* Not first: inserts + rollups + commits are under a third of ingest today. With sharding
   each shard has its own file; Postgres with daily partitions is the step after that.
4. *Approver attention, not compute,* limits how many changes 120 workflows can get per day (fatigue caps).

Faster JSON (orjson) would cut the parse share but adds a dependency to the audited lock file; it is listed, not done.
