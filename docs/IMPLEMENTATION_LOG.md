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

**Milestone 1 — controller core** (`2bffba4`). SQLite store, chunk ingestion (~57k events/s on the dev box),
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

**Milestone 4 — tests, crash harness, load test (subagents + lead).**
- Test suite: 152 tests (151 unit + 1 slow end-to-end). It found real bugs: decay check blind when a workflow has
  no cohort set; minute 0 treated as missing; code/feature caches not reset after a rolled-back transaction;
  floating-point drift against the simulator's exact allocation comparison (`canonical_config`).
- Crash harness: 9 hard kills at state-targeted moments, 20 checks. Found: a paid validation result could be lost
  between the ledger and the incident; a supervisor-prompt probe was forgotten if killed mid-call. Both fixed.
- Comparing crashed vs clean runs exposed a caller-ID decision flaw (volume fatigue mistaken for a spam flag,
  100 % of traffic concentrated on one number). Fixed with an own-history condition.
- Further caller-ID fixes from public_01/02 audits: unknown health never moves traffic; 72 h healthy-only window
  for low-volume probes; re-probe evidence starts at the probe.
- Load test (public_03, final code): ~57k events/s ingest, 69–91 s controller time per simulated day for 12
  workflows, 491 MB peak memory. An hourly week-long scan had doubled decide time; cached per 6 sim-hours.

**Final results** (committed reports): public_01 +15.5 % conclusion rate, 0 harmful of 19 changes; public_02
+26.3 %, 2 harmful of 20 (small exploration costs), caller-ID incident off in ~2 h, unsafe prompt MTTR 60 min;
crash recovery PASS (20 checks, 0 failed) with outcomes matching the uninterrupted run.

## 2026-11-07 (evening) — out-of-sample hardening

**Linux verified in Docker** (`python:3.12-slim`, 4 vCPU / 8 GB): public_01 and public_02 with `run.sh` exit 0.

**Robustness suite** (`scripts/make_robustness_scenarios.py`, `scripts/robustness.sh`): six generated scenarios
(shuffled truth, strict policy, null effects, heavy decay, low credits, odd shapes) × 2 seeds + both public
scenarios, in parallel Linux containers or natively. It exposed and drove fixes for: a flagged caller ID kept at
91 % on an approval-only workflow; decay never tested on a small `next_campaign_only` workflow; an unfixed second
prompt incident at 12 credits; false decay rollbacks from a 5 % test repeated hourly; 20 h MTTR on a
borderline-unsafe prompt; a promotion applied after its effect faded; a false withdrawal from a noisy hourly dip.
Null-effect scenario: 0 harmful changes at both seeds.

**Also:** paging rules as code (`outcomeloop alerts`), read-only HTTP views (`serve-views`), supervisor view in
percentages, `run.sh` path portability (native path via `pwd -W`), review guide (`docs/REVIEW_GUIDE.md`).

**Trade accepted:** ~2–3 points less public_01 lift than the public-only-tuned version, in exchange for the
failure modes above.

## 2026-11-07 (late) — adversarial audit and final evidence

- **Linux re-verified** in Docker on the final commit; **graceful shutdown** added (SIGTERM forwarded by run.sh,
  stop between steps, exit 143) and proven in a container (`scripts/graceful_stop_test.sh`).
- **Independent read-only audit** (20 findings). Fixed: a withdrawn promotion's approval was still applied
  (now WITHDRAWN); our routine approval could stale an incident fix (emergencies apply first); a transient error
  dropped a supervisor event (events retried, workflow held); incidents stuck or blocking (superseded/APPLIED
  handling); cohort-winner family re-spent α (80/20 split); Simpson mixing in the decay test (stratified by
  version); experiments stuck in promoting; rollback urgency lost after an hour; repeated auto-apply 403s;
  confirmation validation not crash-atomic; supervisor caller-ID silently re-spread after the lock; plus low items.
- **The interview-prep review found a KeyError** on pending cohort-level promotions that blocked a workflow's
  decisions every hour (156 errors in one suite run, masked by per-workflow isolation). Fixed, regression test,
  and a new paging rule for a persistently failing workflow. The robustness summary now reports decision errors
  (0 in all 16 final runs) and false winners from our own store (2 in 16 null experiments).
- **Cohort agreement** with the simulator's `cohort_id` is now checked daily (previously claimed, not implemented;
  0 mismatches on 95k calls).
- Final evidence on the final decision logic: public_01 +13.9 % (0 harmful), public_02 +25.6 % (MTTR 60 min),
  load ~55k events/s and 72–89 s controller time per simulated day, crash recovery PASS (20/0), 174 + 2 tests.
