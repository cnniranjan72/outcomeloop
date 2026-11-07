# public_03_load — load test (measured)

Machine: Windows-11-10.0.26300-SP0, 12 logical CPUs, Python 3.12.10. Measured on a 12-logical-CPU Windows 11 laptop; the simulator ran on the same machine; unrelated containers (Kafka, Postgres, Redis, MinIO, Jaeger) were running on the host. Code: commit 51965ce.

All numbers below are read from the controller's own `metrics`/`chunks` tables and the DB file after the run; nothing is estimated unless marked *(derived)*.

## Throughput and latency

| measure | value |
|---|---|
| workflows | 12 |
| history events ingested (pre-D0) | 5,537,379 in 127.1s → 43,550 events/s |
| live events ingested (D0–end) | 4,200,187 in 102.9s → 40,806 events/s |
| peak per-chunk ingest rate | 60,334 events/s |
| call rows stored | 7,433,295 |
| controller time per 15-min tick (ingest + decide), p50 / p95 / max | 0.43s / 1.14s / 17.84s |
| backlog after each tick | 0 chunks: every tick ingests all pending chunks before deciding (the `ingest_lag_minutes` metric, max 660, is time since the last chunk boundary and grows at night when no calls are made, not unprocessed data) |
| peak controller memory (peak working set / max RSS) | 1046 MB |
| SQLite size at end (db + wal) | 433 MB |
| decisions recorded | 737 |
| proposals by state | {'APPLIED': 84, 'PENDING': 1, 'REJECTED': 6} |
| controller wall-clock, whole run incl. waiting on the simulator | 470s |

## Per simulated day

| day | events | ingest s | decide s | controller s (ingest+decide) | simulator advance s | wall s |
|---|---|---|---|---|---|---|
| D0 | 840,056 | 26.3 | 26.9 | 53.3 | 15.8 | 70.4 |
| D1 | 840,045 | 27.6 | 14.8 | 42.4 | 19.8 | 63.6 |
| D2 | 840,036 | 26.8 | 17.2 | 44.0 | 20.3 | 65.3 |
| D3 | 840,024 | 27.8 | 17.6 | 45.4 | 19.7 | 65.8 |
| D4 | 840,026 | 26.5 | 18.9 | 45.3 | 20.5 | 66.6 |

SRE target: ingest and decide on one simulated day in < 10 wall-clock minutes (600 s). The *controller s* column is our share; *simulator advance s* is the simulator generating the world, which in production is the real dialler and does not run on our box.

## Outcomes (sim grade vs no-op baseline)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.397 | +16.3% | 0.267 | +9.3% | 0.527 | +5.2% | 40% | 412 (408) |
| arav_kyc_1 | 0.501 | +41.4% | 0.275 | +28.0% | 0.624 | +4.7% | 27% | 450 (370) |
| arav_renewal_0 | 0.477 | +18.6% | 0.288 | +9.0% | 0.587 | +8.1% | 39% | 481 (440) |
| kest_cancel_2 | 0.392 | +15.7% | 0.266 | +9.2% | 0.524 | +5.2% | 37% | 430 (411) |
| kest_kyc_1 | 0.508 | +43.7% | 0.276 | +28.8% | 0.629 | +5.8% | 33% | 430 (339) |
| kest_renewal_0 | 0.485 | +21.4% | 0.288 | +9.2% | 0.595 | +9.7% | 50% | 465 (433) |
| nort_cancel_2 | 0.396 | +16.9% | 0.266 | +9.6% | 0.528 | +5.8% | 37% | 451 (393) |
| nort_kyc_1 | 0.498 | +40.7% | 0.276 | +29.4% | 0.619 | +3.9% | 23% | 472 (323) |
| nort_renewal_0 | 0.487 | +20.4% | 0.287 | +8.8% | 0.599 | +9.3% | 50% | 473 (411) |
| tide_cancel_2 | 0.395 | +16.4% | 0.266 | +8.8% | 0.527 | +5.6% | 40% | 445 (407) |
| tide_kyc_1 | 0.388 | +9.7% | 0.224 | +4.6% | 0.612 | +3.4% | 14% | 348 (356) |
| tide_renewal_0 | 0.484 | +20.8% | 0.285 | +7.8% | 0.594 | +9.5% | 42% | 491 (438) |
| ALL | 0.451 | +23.5% | 0.272 | +13.0% | 0.580 | +6.8% | 36% | 5348 (4729) |
