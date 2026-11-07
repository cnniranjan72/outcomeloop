# public_03_load — load test (measured)

Machine: Windows-11-10.0.26300-SP0, 12 logical CPUs, Python 3.12.10. Final code. The host was about 2x slower during this run than during earlier load tests: the simulator's own advance time (not our code) was 38-48 s per simulated day here vs 16-26 s before, and controller time rose by about the same factor. Controller/simulator time per day: 1.7-2.8 here, 2.1-3.4 on 51965ce. Compare runs by that ratio, or use the container-capped curve in reports/scaling.md.

All numbers below are read from the controller's own `metrics`/`chunks` tables and the DB file after the run; nothing is estimated unless marked *(derived)*.

## Throughput and latency

| measure | value |
|---|---|
| workflows | 12 |
| history events ingested (pre-D0) | 5,537,379 in 230.3s → 24,039 events/s |
| live events ingested (D0–end) | 4,200,180 in 202.0s → 20,791 events/s |
| peak per-chunk ingest rate | 30,621 events/s |
| call rows stored | 7,433,295 |
| controller time per 15-min tick (ingest + decide), p50 / p95 / max | 0.85s / 1.84s / 40.29s |
| backlog after each tick | 0 chunks: every tick ingests all pending chunks before deciding (the `ingest_lag_minutes` metric, max 660, is time since the last chunk boundary and grows at night when no calls are made, not unprocessed data) |
| peak controller memory (peak working set / max RSS) | 361 MB |
| SQLite size at end (db + wal) | 433 MB |
| decisions recorded | 753 |
| proposals by state | {'APPLIED': 83, 'REJECTED': 1} |
| controller wall-clock, whole run incl. waiting on the simulator | 903s |

## Per simulated day

| day | events | ingest s | decide s | controller s (ingest+decide) | simulator advance s | wall s |
|---|---|---|---|---|---|---|
| D0 | 840,055 | 50.1 | 54.8 | 104.9 | 38.2 | 144.6 |
| D1 | 840,043 | 50.7 | 23.8 | 74.4 | 44.0 | 120.3 |
| D2 | 840,032 | 52.8 | 29.3 | 82.1 | 45.7 | 129.1 |
| D3 | 840,024 | 52.7 | 31.8 | 84.5 | 46.6 | 131.9 |
| D4 | 840,026 | 51.6 | 33.9 | 85.5 | 47.6 | 133.9 |

SRE target: ingest and decide on one simulated day in < 10 wall-clock minutes (600 s). The *controller s* column is our share; *simulator advance s* is the simulator generating the world, which in production is the real dialler and does not run on our box.

## Outcomes (sim grade vs no-op baseline)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.385 | +12.7% | 0.266 | +9.0% | 0.513 | +2.6% | 24% | 465 (408) |
| arav_kyc_1 | 0.508 | +43.6% | 0.276 | +28.5% | 0.628 | +5.5% | 33% | 425 (370) |
| arav_renewal_0 | 0.485 | +20.5% | 0.287 | +8.8% | 0.597 | +9.8% | 50% | 466 (440) |
| kest_cancel_2 | 0.390 | +15.1% | 0.267 | +9.7% | 0.518 | +3.9% | 26% | 425 (411) |
| kest_kyc_1 | 0.509 | +44.1% | 0.276 | +28.8% | 0.629 | +5.8% | 33% | 422 (339) |
| kest_renewal_0 | 0.492 | +23.1% | 0.289 | +9.7% | 0.597 | +10.1% | 49% | 464 (433) |
| nort_cancel_2 | 0.403 | +19.0% | 0.266 | +9.7% | 0.536 | +7.4% | 49% | 447 (393) |
| nort_kyc_1 | 0.504 | +42.4% | 0.274 | +28.3% | 0.628 | +5.5% | 33% | 443 (323) |
| nort_renewal_0 | 0.484 | +19.6% | 0.286 | +8.7% | 0.597 | +8.9% | 49% | 437 (411) |
| tide_cancel_2 | 0.404 | +19.1% | 0.265 | +8.6% | 0.538 | +7.7% | 52% | 441 (407) |
| tide_kyc_1 | 0.411 | +16.4% | 0.235 | +9.7% | 0.613 | +3.6% | 17% | 387 (356) |
| tide_renewal_0 | 0.477 | +19.0% | 0.283 | +7.2% | 0.590 | +8.8% | 37% | 453 (438) |
| ALL | 0.454 | +24.5% | 0.273 | +13.3% | 0.582 | +7.1% | 38% | 5275 (4729) |
