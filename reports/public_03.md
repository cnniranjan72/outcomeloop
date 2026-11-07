# public_03_load — load test (measured)

Machine: Windows-11-10.0.26300-SP0, 12 logical CPUs, Python 3.12.10. Measured on a 12-logical-CPU Windows 11 laptop; the simulator ran on the same machine, nothing else heavy running. Code: commit b42a409.

All numbers below are read from the controller's own `metrics`/`chunks` tables and the DB file after the run; nothing is estimated unless marked *(derived)*.

## Throughput and latency

| measure | value |
|---|---|
| workflows | 12 |
| history events ingested (pre-D0) | 5,537,379 in 171.8s → 32,226 events/s |
| live events ingested (D0–end) | 4,200,145 in 74.3s → 56,514 events/s |
| peak per-chunk ingest rate | 87,070 events/s |
| call rows stored | 7,433,295 |
| controller time per 15-min tick (ingest + decide), p50 / p95 / max | 0.32s / 3.85s / 19.83s |
| backlog after each tick | 0 chunks: every tick ingests all pending chunks before deciding (the `ingest_lag_minutes` metric, max 660, is time since the last chunk boundary and grows at night when no calls are made, not unprocessed data) |
| peak controller memory (peak working set / max RSS) | 491 MB |
| SQLite size at end (db + wal) | 363 MB |
| decisions recorded | 462 |
| proposals by state | {'APPLIED': 49, 'REJECTED': 3} |
| controller wall-clock, whole run incl. waiting on the simulator | 677s |

## Per simulated day

| day | events | ingest s | decide s | controller s (ingest+decide) | simulator advance s | wall s |
|---|---|---|---|---|---|---|
| D0 | 840,053 | 19.4 | 55.1 | 74.5 | 15.7 | 91.5 |
| D1 | 840,035 | 19.5 | 49.1 | 68.6 | 18.0 | 87.9 |
| D2 | 840,021 | 19.1 | 71.7 | 90.9 | 19.6 | 111.1 |
| D3 | 840,016 | 20.0 | 59.5 | 79.5 | 19.8 | 99.9 |
| D4 | 840,020 | 19.8 | 63.1 | 82.9 | 20.3 | 103.9 |

SRE target: ingest and decide on one simulated day in < 10 wall-clock minutes (600 s). The *controller s* column is our share; *simulator advance s* is the simulator generating the world, which in production is the real dialler and does not run on our box.

## Outcomes (sim grade vs no-op baseline)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.396 | +16.1% | 0.266 | +8.9% | 0.529 | +5.7% | 40% | 405 (408) |
| arav_kyc_1 | 0.503 | +42.2% | 0.274 | +27.5% | 0.627 | +5.3% | 34% | 482 (370) |
| arav_renewal_0 | 0.489 | +21.5% | 0.289 | +9.4% | 0.596 | +9.7% | 49% | 486 (440) |
| kest_cancel_2 | 0.391 | +15.4% | 0.266 | +9.3% | 0.522 | +4.6% | 34% | 449 (411) |
| kest_kyc_1 | 0.497 | +40.6% | 0.276 | +28.9% | 0.616 | +3.6% | 23% | 449 (339) |
| kest_renewal_0 | 0.484 | +21.1% | 0.287 | +9.0% | 0.595 | +9.7% | 50% | 481 (433) |
| nort_cancel_2 | 0.405 | +19.4% | 0.266 | +9.7% | 0.537 | +7.7% | 49% | 447 (393) |
| nort_kyc_1 | 0.505 | +42.6% | 0.274 | +28.4% | 0.628 | +5.4% | 33% | 432 (323) |
| nort_renewal_0 | 0.484 | +19.6% | 0.287 | +9.1% | 0.595 | +8.6% | 50% | 460 (411) |
| tide_cancel_2 | 0.391 | +15.2% | 0.265 | +8.5% | 0.523 | +4.7% | 31% | 397 (407) |
| tide_kyc_1 | 0.413 | +16.8% | 0.235 | +9.6% | 0.616 | +4.0% | 20% | 386 (356) |
| tide_renewal_0 | 0.473 | +18.0% | 0.282 | +6.9% | 0.588 | +8.4% | 37% | 422 (438) |
| ALL | 0.452 | +24.0% | 0.272 | +13.2% | 0.581 | +6.9% | 38% | 5296 (4729) |
