# Measured scaling: 1× vs 3× public_03

Generated with `scripts/scaling.sh`: `scripts/make_scale_scenario.py` makes K copies of every public_03
workflow under new ids (2 simulated days, shortened history); each run is a Linux container at the
grader's spec (`--cpus 4 --memory 8g`, `scripts/docker_scenario.sh`), one after the other, same code
(commit `d1cbfcd`; the image was built from it before any later edit). Every number is read from that run's
own `metrics` / `chunks` tables by `scripts/scale_report.py`. Other containers ran on the host, so
absolute times are conservative; the ratio is the point.

| | 1× (12 workflows) | 3× (36 workflows) | ratio |
|---|---|---|---|
| events per simulated day | 840,055 / 840,039 | 2,520,171 / 2,520,129 | 3.0× |
| ingest seconds per simulated day | 27.2 / 27.4 | 76.9 / 72.0 | 2.7× |
| decide seconds per simulated day | 21.3 / 21.7 | 65.1 / 63.8 | 3.0× |
| **controller seconds per simulated day** | **48.6 / 49.1** | **142.0 / 135.8** | **2.8×** |
| simulator seconds per simulated day (not ours) | 19.3 / 24.7 | 61.7 / 57.9 | |
| history ingest throughput | 47,052 events/s | 46,193 events/s | |
| live ingest throughput | 38,679 events/s | 41,254 events/s | |
| per-tick controller time p95 / max | 1.24 s / 9.3 s | 3.72 s / 26.8 s | |
| peak memory (ru_maxrss) | 272 MB | 345 MB | 1.27× |
| SQLite file at end | 177 MB | 536 MB | 3.0× |
| decision errors | 0 | 0 | |

Reading it:

* Controller cost grew 2.8× for 3× the events and workflows.
* *Projection, not a measurement:* scaling the measured per-unit cost linearly to 10× public_03
  (≈ 8.4 M events/day, 120 workflows) gives ≈ **463 s of controller time per simulated day** on
  4 vCPU, against the 600 s target. Where the time goes and what changes first: see below.

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

## Sharding prototype (measured): ingest split across processes by workflow

`scripts/bench_shards.py`: N processes each ingest only their workflows (`shard_of` = sha256(workflow_id) mod N) from the
first 8 public_03 history chunks (2,000,000 events) of one running simulator, each into its own store, all at once.
A shard pre-filters raw lines by `workflow_id` before JSON parsing (`Ingestor(workflows=...)`), so it parses only its own
events. Same 12-CPU laptop and host conditions as the final load run.

| shards | wall s | per-shard s (workflows) | events/s (aggregate) | speed-up | call rows |
|---|---|---|---|---|---|
| 1 | 81.7 | 80.32 (12) | 24,489 | 1.00× | 1,423,964 same |
| 2 | 58.0 | 42.34 (5), 56.35 (7) | 34,501 | 1.41× | 1,423,964 same |
| 4 | 53.4 | 37.80 (2), 51.84 (4), 45.28 (3), 45.51 (3) | 37,423 | 1.53× | 1,423,964 same |

* **Correct:** the shards together stored exactly the rows one process stores (1,423,964 call rows) at every N.
* **Faster, but sub-linear:** 1.41× with 2 shards, 1.53× with 4. Two measured reasons: every shard still downloads the
  whole chunk from one simulator process and scans every line, and workflows are coarse (12 here, so 4 shards split them
  2/4/3/3 and the slowest shard sets the wall time). The production shape is one reader per stream fanning out raw
  lines (or the dialler partitioning its event stream by workflow), and many more workflows than shards.
* **Not wired into `run.sh`:** the controller has one clock (`/sim/advance`) and one credit pool. A sharded deployment
  needs a coordinator that advances time once every shard has finished its tick, and a shared credit ledger (the fair-
  share rule already exists). This prototype measures the part that breaks first; it is not a claim that 10× is solved.
