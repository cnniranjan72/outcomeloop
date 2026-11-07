# public_03_load — load test (measured)

Machine: Windows-11-10.0.26300-SP0, 12 logical CPUs, Python 3.12.10. Measured on a 12-logical-CPU Windows 11 laptop; the simulator ran on the same machine, nothing else heavy running. Code: commit b36c7a6.

All numbers below are read from the controller's own `metrics`/`chunks` tables and the DB file after the run; nothing is estimated unless marked *(derived)*.

## Throughput and latency

| measure | value |
|---|---|
| workflows | 12 |
| history events ingested (pre-D0) | 5,537,379 in 85.8s → 64,508 events/s |
| live events ingested (D0–end) | 4,200,155 in 71.2s → 59,014 events/s |
| peak per-chunk ingest rate | 94,750 events/s |
| call rows stored | 7,433,295 |
| controller time per 15-min tick (ingest + decide), p50 / p95 / max | 0.33s / 3.03s / 19.95s |
| backlog after each tick | 0 chunks: every tick ingests all pending chunks before deciding (the `ingest_lag_minutes` metric, max 660, is time since the last chunk boundary and grows at night when no calls are made, not unprocessed data) |
| peak controller memory (peak working set / max RSS) | 490 MB |
| SQLite size at end (db + wal) | 363 MB |
| decisions recorded | 476 |
| proposals by state | {'APPLIED': 55, 'PENDING': 1, 'REJECTED': 3} |
| controller wall-clock, whole run incl. waiting on the simulator | 565s |

## Per simulated day

| day | events | ingest s | decide s | controller s (ingest+decide) | simulator advance s | wall s |
|---|---|---|---|---|---|---|
| D0 | 840,056 | 19.6 | 54.9 | 74.5 | 15.5 | 91.4 |
| D1 | 840,038 | 21.4 | 48.7 | 70.1 | 17.9 | 89.5 |
| D2 | 840,032 | 21.0 | 55.3 | 76.3 | 19.1 | 96.7 |
| D3 | 840,014 | 20.3 | 52.1 | 72.4 | 19.7 | 92.8 |
| D4 | 840,015 | 21.7 | 57.6 | 79.3 | 20.0 | 100.2 |

SRE target: ingest and decide on one simulated day in < 10 wall-clock minutes (600 s). The *controller s* column is our share; *simulator advance s* is the simulator generating the world, which in production is the real dialler and does not run on our box.

## Outcomes (sim grade vs no-op baseline)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.398 | +16.7% | 0.266 | +9.0% | 0.531 | +6.1% | 49% | 453 (408) |
| arav_kyc_1 | 0.502 | +41.8% | 0.275 | +28.4% | 0.621 | +4.3% | 27% | 431 (370) |
| arav_renewal_0 | 0.486 | +20.8% | 0.286 | +8.3% | 0.600 | +10.5% | 51% | 434 (440) |
| kest_cancel_2 | 0.381 | +12.6% | 0.260 | +6.7% | 0.524 | +5.0% | 36% | 430 (411) |
| kest_kyc_1 | 0.503 | +42.3% | 0.274 | +28.2% | 0.626 | +5.4% | 33% | 427 (339) |
| kest_renewal_0 | 0.478 | +19.7% | 0.285 | +8.3% | 0.593 | +9.3% | 46% | 460 (433) |
| nort_cancel_2 | 0.396 | +16.8% | 0.265 | +9.5% | 0.528 | +5.8% | 39% | 418 (393) |
| nort_kyc_1 | 0.502 | +41.9% | 0.273 | +28.2% | 0.628 | +5.5% | 33% | 408 (323) |
| nort_renewal_0 | 0.478 | +18.1% | 0.286 | +8.4% | 0.592 | +8.0% | 47% | 478 (411) |
| tide_cancel_2 | 0.401 | +18.3% | 0.265 | +8.5% | 0.536 | +7.4% | 48% | 403 (407) |
| tide_kyc_1 | 0.448 | +26.8% | 0.251 | +17.1% | 0.618 | +4.4% | 20% | 433 (356) |
| tide_renewal_0 | 0.477 | +19.1% | 0.284 | +7.3% | 0.589 | +8.5% | 41% | 461 (438) |
| ALL | 0.454 | +24.4% | 0.273 | +13.4% | 0.583 | +7.2% | 39% | 5236 (4729) |
