# Adversarial review — trying to reject the submission

Written as a reviewer looking for a reason to say no. Each attempt names how it was tried, what it found, and the
fix or the evidence that it holds. Attacks on the controller itself (39 of them) are in `ADVERSARIAL_TESTING.md`;
this report covers the claims, the evidence and the tests.

| # | attempt | how | result | evidence / fix |
|---|---|---|---|---|
| 1 | Find a false winner | Recount every winner's look from raw calls; null scenario over two seeds | Recounts match the stored n, z, p and the Holm result exactly; 0 winners in 12 experiments with no true effect | `replay <id>` (public_01 #133: W3 z 2.60, Holm ✓, W2 ✗); `reports/robustness.md` |
| 2 | Show a run is not reproducible | Run public_02 twice with different controller hash seeds against identically seeded simulators | **Found:** the caller-ID ramp built its allocation from set iteration; the simulator samples by key order, so the world diverged between runs (26 vs 29 changes, same headline) | Fixed (`b99b660`); `scripts/determinism_check.sh`: 284 = 284 decisions, 491 identical event chunks; regression assertion fails on the unfixed code for every hash seed tried |
| 3 | Find a test that passes without checking anything | Grep for `or`-guarded assertions and tests without assertions | **Found:** a verifier test whose exit-code assertion was always true for INCOMPLETE faults; it hid a fault that was also an unacknowledged supervisor edit | Fixed (`f6986c5`); no test without an assertion remains |
| 4 | Find a supervisor edit that was overwritten | `verify`: every supervisor config version must have its `supervisor_edit` decision; apply checks the base version | VALID on both public stores; STALE proposals are never applied | `verify` check 7; `test_supervisor_edit_between_approval_and_apply_is_never_overwritten` |
| 5 | Find a change that bypassed governance | `verify`: every controller config version = exactly one APPLIED proposal, approval id matching the config history | VALID (26 and 29 controller versions) | `verify` check 4; crash report check 3 |
| 6 | Find a double-counted event | `verify`: event ids contiguous across chunks, one call row per event; replay ingestion twice | VALID; idempotent replay tested | `verify` checks 1–2; `test_ingest_all_and_idempotent_replay` |
| 7 | Crash into an inconsistent state | 9 SIGKILLs at chosen boundaries, then 20 checks; `verify` after the run | 0 failed; no proposal left uncertain | `reports/crash_recovery.md`; `verify` checks 5 and 11 |
| 8 | Find a decision that cannot be reconstructed | `replay` on an experiment winner, a caller-ID degradation and a prompt incident | Each recomputed from persisted rows (raw calls, detector re-run, credits ledger) and matched | `evidence/DECISION_EVIDENCE.md`; `tests/unit/test_verify.py` (tampered evidence → INVALID) |
| 9 | Find a documented command that does not exist | Every `python -m outcomeloop <cmd>` in the docs against the CLI | All exist | — |
| 10 | Find a claim stronger than the code | Grep for "exactly once", "guarantee", "deterministic" | "Exactly once" is claimed for ingestion only (verified); decisions are deterministic given the data; run-level reproducibility was **not** true until attempt 2's fix | Credit calls are not exactly-once (≤ 3 credits can be double-spent after a crash) — stated in `ADVERSARIAL_TESTING.md` §6 |
| 11 | Find a benchmark that cannot be reproduced | Re-run the load and ingest benchmarks | Laptop numbers vary with host load (one run was ~2× slower; the simulator slowed equally, which the report states); container numbers and the scripts are reproducible | `reports/public_03.md` note; `scripts/scaling.sh`, `scripts/bench_ingest.py`, `scripts/evaluate.py` |
| 12 | Find a principled-sounding change that does not help | A/B every outcome change on 16 robustness runs before keeping it | **Found:** "heightened watch" for prompts not shown safe — no MTTR gain, +1 harmful; reverted, not committed | `CONTINUOUS_IMPROVEMENT_LOG.md` (not done) |

## What a reviewer can still legitimately push on

- 10× is projected from a measured 1×/3× curve; sharding is a measured prototype, not wired into `run.sh`.
- Post-apply verification is before/after on the whole workflow (time-confounded): a check, not an effect estimate.
- Exploration costs appear as "harmful" grader verdicts (one in the final public_02 run).
- A small decay late in a run may not be rolled back before the run ends.
