# public_03_load — load test (measured)

Machine: Windows-11-10.0.26300-SP0, 12 logical CPUs, Python 3.12.10. Measured on a 12-logical-CPU Windows 11 laptop; the simulator ran on the same machine, nothing else heavy running. Code: commit 1b1894d.

All numbers below are read from the controller's own `metrics`/`chunks` tables and the DB file after the run; nothing is estimated unless marked *(derived)*.

## Throughput and latency

| measure | value |
|---|---|
| workflows | 12 |
| history events ingested (pre-D0) | 5,537,379 in 83.1s → 66,669 events/s |
| live events ingested (D0–end) | 4,200,148 in 75.8s → 55,375 events/s |
| peak per-chunk ingest rate | 76,127 events/s |
| call rows stored | 7,433,295 |
| controller time per 15-min tick (ingest + decide), p50 / p95 / max | 0.33s / 3.17s / 19.79s |
| backlog after each tick | 0 chunks: every tick ingests all pending chunks before deciding (the `ingest_lag_minutes` metric, max 660, is time since the last chunk boundary and grows at night when no calls are made, not unprocessed data) |
| peak controller memory (peak working set / max RSS) | 494 MB |
| SQLite size at end (db + wal) | 391 MB |
| decisions recorded | 452 |
| proposals by state | {'APPLIED': 51, 'REJECTED': 2} |
| controller wall-clock, whole run incl. waiting on the simulator | 593s |

## Per simulated day

| day | events | ingest s | decide s | controller s (ingest+decide) | simulator advance s | wall s |
|---|---|---|---|---|---|---|
| D0 | 840,053 | 19.3 | 54.7 | 74.0 | 15.4 | 90.3 |
| D1 | 840,037 | 19.9 | 52.5 | 72.4 | 18.6 | 92.3 |
| D2 | 840,026 | 20.3 | 61.9 | 82.2 | 19.6 | 102.8 |
| D3 | 840,016 | 21.0 | 64.6 | 85.6 | 19.6 | 105.9 |
| D4 | 840,016 | 22.1 | 67.1 | 89.2 | 19.9 | 109.7 |

SRE target: ingest and decide on one simulated day in < 10 wall-clock minutes (600 s). The *controller s* column is our share; *simulator advance s* is the simulator generating the world, which in production is the real dialler and does not run on our box.

## Outcomes (sim grade vs no-op baseline)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.396 | +16.1% | 0.265 | +8.6% | 0.529 | +5.8% | 40% | 438 (408) |
| arav_kyc_1 | 0.502 | +41.9% | 0.275 | +28.1% | 0.624 | +4.8% | 33% | 413 (370) |
| arav_renewal_0 | 0.482 | +19.9% | 0.287 | +8.7% | 0.593 | +9.2% | 47% | 434 (440) |
| kest_cancel_2 | 0.398 | +17.6% | 0.265 | +8.9% | 0.532 | +6.7% | 46% | 445 (411) |
| kest_kyc_1 | 0.509 | +44.1% | 0.276 | +29.1% | 0.629 | +5.8% | 33% | 440 (339) |
| kest_renewal_0 | 0.488 | +22.0% | 0.289 | +9.6% | 0.596 | +9.9% | 51% | 438 (433) |
| nort_cancel_2 | 0.394 | +16.4% | 0.265 | +9.2% | 0.528 | +5.8% | 38% | 427 (393) |
| nort_kyc_1 | 0.501 | +41.5% | 0.274 | +28.6% | 0.624 | +4.8% | 27% | 447 (323) |
| nort_renewal_0 | 0.478 | +18.1% | 0.284 | +7.9% | 0.594 | +8.4% | 49% | 467 (411) |
| tide_cancel_2 | 0.385 | +13.5% | 0.265 | +8.7% | 0.515 | +3.2% | 32% | 408 (407) |
| tide_kyc_1 | 0.407 | +15.2% | 0.234 | +9.0% | 0.611 | +3.2% | 17% | 409 (356) |
| tide_renewal_0 | 0.479 | +19.5% | 0.283 | +7.1% | 0.593 | +9.3% | 41% | 452 (438) |
| ALL | 0.452 | +23.8% | 0.272 | +13.1% | 0.581 | +6.9% | 38% | 5218 (4729) |
