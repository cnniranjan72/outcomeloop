# Load-test memory: what grew, why, and the fix (measured)

**Symptom.** Peak controller memory on public_03 rose from 494 MB to 1,046 MB between two evidence runs.

**Where in the run.** The controller records its peak working set every tick (`metrics.rss_mb`). On the 1,046 MB
run the series is already at 1,046 at the first live tick (D0 01:00) and flat to the end: the peak is reached during
start-up history ingestion (5.5 M events in 250,000-event chunks), not in the decision loop.

**What, measured in isolation** (one public_03 history chunk, fresh process each, peak working set delta):

| operation | extra peak memory |
|---|---|
| parse one 250k-event chunk into a list of dicts (what `iter_chunk` did after the partial-response fix) | **+487 MB** |
| stream the same chunk, one event at a time | +1 MB |
| build the person feature store (1.68 M persons) — `fetchall()` of the rows, not the arrays (10 MB) | +260 MB |

The partial-response hardening (adversarial test #12) parsed a whole chunk before yielding anything, so a truncated
response could never be half-ingested. That alone accounts for the rise.

**Fix.**
- Chunks stream again. An incomplete read — transport error, malformed line, 5xx, or fewer events than the chunk
  listing says — raises `ChunkReadError`; `Ingestor.ingest_chunk` rolls that chunk's transaction back and re-reads
  it whole, bounded. Atomicity comes from the transaction, which is where it always was. The event-count check also
  catches a response cut exactly at a line boundary, which the buffered version missed.
- The feature store sizes its arrays from `MAX(person)` and streams rows from the cursor. A failed chunk undoes only
  the persons it added (`FeatureStore.forget`) instead of rebuilding the store.

**Result** (same scenario, same machine, full load test; `reports/public_03.md`):

| | before (51965ce) | after (streaming) |
|---|---|---|
| peak controller memory | 1,046 MB | **360 MB** |
| history ingest | 43,550 events/s | 56,940 events/s |
| live ingest | 40,806 events/s | 43,012 events/s |
| tick p50 / p95 | 0.43 s / 1.14 s | 0.39 s / 1.09 s |
| conclusion rate vs no-op | +23.5 % | +23.6 % |

Both runs on the 12-CPU Windows laptop with the simulator on the same host; other containers were running, so
per-day seconds vary by a few seconds between runs. Tests: `test_partial_chunk_is_rolled_back_and_reread_whole`
(mid-line and line-boundary cuts), `test_truncated_or_short_chunk_raises_chunk_read_error`,
`test_chunk_that_never_reads_completely_fails_loudly_and_keeps_nothing`.
