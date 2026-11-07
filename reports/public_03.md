# public_03_load — load test (measured)

Machine: Windows-11-10.0.26300-SP0, 12 logical CPUs, Python 3.12.10. Final code. The host was about 2x slower during this run than during earlier load tests: the simulator's own advance time (not our code) was 39-47 s per simulated day here vs 16-26 s before, and controller time rose by about the same factor (controller/simulator ratio 1.7-2.8 here, 2.1-3.4 on 51965ce). Compare runs by that ratio, or use the container-capped curve in reports/scaling.md (48.6-49.1 s per simulated day at 1x on 4 vCPU).

All numbers below are read from the controller's own `metrics`/`chunks` tables and the DB file after the run; nothing is estimated unless marked *(derived)*.

## Throughput and latency

| measure | value |
|---|---|
| workflows | 12 |
| history events ingested (pre-D0) | 5,537,379 in 220.1s → 25,164 events/s |
| live events ingested (D0–end) | 4,200,178 in 194.4s → 21,609 events/s |
| peak per-chunk ingest rate | 31,844 events/s |
| call rows stored | 7,433,295 |
| controller time per 15-min tick (ingest + decide), p50 / p95 / max | 0.84s / 1.74s / 40.55s |
| backlog after each tick | 0 chunks: every tick ingests all pending chunks before deciding (the `ingest_lag_minutes` metric, max 660, is time since the last chunk boundary and grows at night when no calls are made, not unprocessed data) |
| peak controller memory (peak working set / max RSS) | 360 MB |
| SQLite size at end (db + wal) | 433 MB |
| decisions recorded | 748 |
| proposals by state | {'APPLIED': 82, 'REJECTED': 1} |
| controller wall-clock, whole run incl. waiting on the simulator | 877s |

## Per simulated day

| day | events | ingest s | decide s | controller s (ingest+decide) | simulator advance s | wall s |
|---|---|---|---|---|---|---|
| D0 | 840,055 | 51.6 | 55.8 | 107.5 | 38.9 | 148.1 |
| D1 | 840,043 | 49.5 | 23.6 | 73.1 | 42.7 | 117.7 |
| D2 | 840,032 | 50.7 | 26.7 | 77.5 | 44.3 | 123.0 |
| D3 | 840,024 | 50.0 | 29.1 | 79.2 | 44.9 | 124.8 |
| D4 | 840,024 | 50.8 | 32.7 | 83.5 | 46.8 | 131.0 |

SRE target: ingest and decide on one simulated day in < 10 wall-clock minutes (600 s). The *controller s* column is our share; *simulator advance s* is the simulator generating the world, which in production is the real dialler and does not run on our box.

## Outcomes (sim grade vs no-op baseline)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.395 | +15.8% | 0.266 | +8.9% | 0.527 | +5.3% | 40% | 443 (408) |
| arav_kyc_1 | 0.505 | +42.5% | 0.274 | +27.9% | 0.628 | +5.4% | 33% | 432 (370) |
| arav_renewal_0 | 0.486 | +20.8% | 0.287 | +8.7% | 0.598 | +10.1% | 48% | 465 (440) |
| kest_cancel_2 | 0.402 | +18.7% | 0.266 | +9.5% | 0.533 | +6.9% | 49% | 413 (411) |
| kest_kyc_1 | 0.501 | +41.9% | 0.274 | +28.3% | 0.623 | +4.9% | 30% | 462 (339) |
| kest_renewal_0 | 0.483 | +20.9% | 0.287 | +8.9% | 0.594 | +9.5% | 48% | 466 (433) |
| nort_cancel_2 | 0.404 | +19.4% | 0.266 | +9.6% | 0.537 | +7.6% | 51% | 410 (393) |
| nort_kyc_1 | 0.504 | +42.3% | 0.273 | +28.0% | 0.629 | +5.6% | 33% | 449 (323) |
| nort_renewal_0 | 0.480 | +18.7% | 0.286 | +8.4% | 0.595 | +8.7% | 49% | 439 (411) |
| tide_cancel_2 | 0.406 | +19.6% | 0.267 | +9.3% | 0.535 | +7.2% | 49% | 441 (407) |
| tide_kyc_1 | 0.415 | +17.4% | 0.236 | +10.1% | 0.616 | +4.0% | 20% | 375 (356) |
| tide_renewal_0 | 0.484 | +20.7% | 0.284 | +7.7% | 0.596 | +9.8% | 42% | 463 (438) |
| ALL | 0.455 | +24.8% | 0.272 | +13.2% | 0.584 | +7.5% | 41% | 5258 (4729) |
