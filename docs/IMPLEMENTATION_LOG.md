# Implementation log

Short, dated record of what was built, what was run, what it showed, and what changed because of it.
All "results" lines refer to files in `reports/` produced by `scripts/run_scenario.sh`.

## 2026-11-07

**Reconnaissance.** Read the assignment, `docs/SIMULATOR.md`, the six memos, scenario schemas and the HTTP
contract. Key contract facts that shaped the design: dims are sampled independently per dial (factorial
experiments are free); approvals cannot be withdrawn (one open proposal per workflow); the approver's
latency/hours/TTL are published per workflow (submission timing can be computed, not guessed); `event_id`
is strictly increasing and chunks stay re-listable (exactly-once ingestion via checkpoint-in-transaction).
Baselines generated for all three public scenarios.

**Milestone 1 — controller core** (`2bffba4`). SQLite store, chunk ingestion (~59k events/s on the dev box),
shared cohort object bootstrapped from history, caller-ID and hallucination detectors, factorial
welcome/voice experiments with O'Brien-Fleming spending and Holm, governance client with crash-safe
reconcile, CLI views. First public_01 run: +12.3 % conclusion rate vs baseline, but 4 harmful changes.

**Milestone 2 — defects found by reading our own audit trail** (`ecdf450`).
- Experiments only saw the first config version's calls: version appends were not persisted. Fixed.
- A hallucination "incident" on the production prompt was a QA-flag tail event; the fix chosen (the strict
  script) cut engagement 14 %. Now: incidents need a second signal (validation run of the live prompt), and
  fixes are verified on engagement after apply.
- A winner was promoted after its effect had already faded. Added a recent-window stability check.
- A good winner was rolled back by the decay test (winner's curse: the promotion estimate is inflated).
  Decay is now tested against the promotion's 80 % lower confidence bound.
- Caller-ID flip-flops: "unknown" with plenty of data was treated as probe-only; degraded was permanent.
  Now measured-and-fine = healthy; degraded numbers rest, then get a time-boxed 2 % re-probe.
- Re-testing an arm that had just been dropped as harmful. Dropped/decayed arms are blacklisted for 7 days.
- Supervisor prompt edits now trigger an immediate decision (public_02 MTTR 180 → 60 min).

**Milestone 3** (`9663c9b`). "Healthy" caller ID now needs the ratio's ~84 % lower bound ≥ 0.85 (a 0.55-health
number had slipped through on 168 dials). Pre-registered single experiment extension with an explicit alpha
budget, because under-powered tests ending in "revert to incumbent" were harmful when the challenger was
genuinely better. Per-phase timing metrics for the load test.
Results at this point: public_01 +17.0 % conclusion rate, 0 harmful; public_02 +28.3 %, 2 harmful
(small exploration costs), DID incident handled within 2 h, bad-prompt MTTR 60–120 min.

**Robustness.** Per-workflow / per-phase / per-event exception isolation (an unexpected error is audited and
the loop continues); `run.sh` restarts the controller from durable state if it ever exits abnormally.

**In parallel (subagents):** test suite, crash-recovery harness, README/architecture/operations docs and video
materials. Load test on public_03.
