## 8. Scale

Measured on `public_03_load` (12 workflows, ~840k events/day) with `scripts/load_test.sh`; full report in
`reports/public_03.md`. {{LOAD_MACHINE}}

| measure | value |
|---|---|
{{LOAD_TABLE}}

**Decision lag.** In simulated time a detector sees an event at most 15 min (one tick) after it happens and
decides at most 60 min later (hourly cadence); a supervisor prompt edit triggers a decision on the next tick.
In wall-clock time the controller's own work per 15-minute tick is {{LOAD_TICK}} (ingest + all decisions for
12 workflows); against a real dialler that is the end-to-end lag added by us.

**SRE's target** (one simulated day in < 10 wall-clock minutes on 4 vCPU / 8 GB): our share is
{{LOAD_CTRL_DAY}} per simulated day on a laptop; the rest of the wall time is the simulator generating the
world. Memory stays small because analysis is SQL over an on-disk table; only per-person feature arrays
(1 int32 per person) live in RAM.

**What breaks first at 10× (≈ 8.5 M events/day, 120 workflows)** *(derived from the measurements above)*:
1. **Per-tick decision queries.** Decisions are ~60 % of our time and scale with workflows × raw rows scanned
   (experiment and detector windows are SQL over raw call rows). At 10× that is ~10× the decide time: still
   inside a 15-min tick but no longer comfortable. Fix: per-(workflow, hour, cohort, variant, caller ID)
   rollups maintained at ingest, so a decision reads hundreds of rows, not hundreds of thousands.
2. **One SQLite writer.** Ingest at ~50k events/s is ~3 min/day at 10× — fine — but one process serialises
   ingest and decisions. Fix: partition workflows into shards (hash of `workflow_id`), one loop + checkpoint per
   shard, on the platform's Postgres with `calls` partitioned by day.
3. **Storage.** ~{{LOAD_BYTES_PER_EVENT}} bytes per stored call row → ~{{LOAD_GB_MONTH}} GB/month at 10×. Retention
   policy with Compliance; rollups kept, raw calls archived after the audit window.
4. **Credits and approver attention** become shared resources across 100+ workflows (C15, cut): per-tenant
   budgets ranked by impact score.

## 9. Reliability

* **Crash-recovery test** (`scripts/crash_recovery.sh`, report `reports/crash_recovery.md`): one run of
  public_02, the controller hard-killed **9 times** with SIGKILL / TerminateProcess at state-targeted moments —
  during history ingestion, with a proposal pending, with an approval approved-but-not-applied, mid-dial, with a
  paid validation call in flight, at the supervisor's edit, with a proposal submit in flight — and restarted
  against the same SQLite file each time. **{{CRASH_LINE}}** Checks include: every chunk ingested exactly
  once (event counts equal to the simulator's), calls table equal to the simulator's call events, no proposal or
  approval applied twice, every simulator approval known to our store, nothing left in an uncertain state,
  experiments and incidents not duplicated and continuing under the same ids, credits accounted for, run finished.
  Outcomes under kills: {{CRASH_OUTCOME}}.
* **The test found three real defects**, all fixed: a paid validation result could be lost between the ledger
  and the incident (now one transaction); a supervisor-prompt probe was cleared before the validation call, so a
  crash forgot a pending safety check (now cleared in the same transaction as the result); and a caller-ID
  decision flaw that only showed up by comparing crashed vs clean runs (§5).
* **Graceful shutdown.** SIGTERM/SIGINT (deploys, `docker stop`) are forwarded by `run.sh` to the controller,
  which finishes the current step, records `controller_stop` and exits 143; `run.sh` restarts only on an
  *unrequested* exit. Verified in a Linux container (`scripts/graceful_stop_test.sh`): SIGTERM at D4 11:15 → clean
  stop with no proposal in an uncertain state → restart on the same DB finishes with exactly-once ingestion.
* **Events are never dropped.** A side-effect event (`config_changed`, `approval_decided`) whose handler hits a
  transient error is retried next tick; later events of that workflow wait, and the workflow gets no decisions
  until its events are processed (a lost supervisor edit would mean overwriting it). Dead-lettered with an
  audited error only after 10 attempts.
* **Adversarial review.** An independent read-only audit of the code (fresh eyes, prompted to find crash-safety,
  governance, statistical and performance defects) reported 20 findings; the 3 high and 8 medium ones are fixed and
  the high ones have regression tests (e.g. a withdrawn promotion's approval was still being applied; our own
  routine approval could make an incident fix stale; the cohort-winner family re-spent the look's α).
* **What a crash loses.** Nothing durable. In flight at the instant of the kill: at most one HTTP response
  (reconciled on restart), and for a credit-spending call (no idempotency key in the API) up to 3 credits may be
  spent twice.
* **Idempotency keys.** Chunk number + `event_id` (ingestion); deterministic `proposal_id`
  (`ol-<workflow>-<sim minute>-<seq>`) committed before submit and auto-apply; `approval_id` for apply.
* **Simulator errors.** GETs retried with back-off on connection errors/5xx. Writes: a connection refused
  before sending is retried; a timeout or 5xx after sending raises `Uncertain` and is reconciled against
  `/approvals` or `/config/history` — never assumed failed. 409 `stale_base_version` → re-plan on the new base;
  410 lapsed → recorded, re-planned; 409 `duplicate_proposal_id` → reconcile (it landed earlier); 403 auto-apply →
  recorded, the change waits for the approval route; 402 credits → incident work stops spending, routine work
  never spends below the 40 % reserve. Any unexpected exception in one workflow's decision is audited and isolated;
  `run.sh` restarts the controller from durable state if the process itself dies.

## 10. Audit & observability

The review question, answered from our store only (real output, public_02, trimmed):

```
$ python -m outcomeloop --db state/public_02_incidents.db why ks_cancel --at "D3 12:30"
{{WHY_OUTPUT}}
```

Other questions the store answers: `customer <person_id> --day N` (what a customer heard on each call, under which
config version, set by which proposal/approval — Compliance's IRDAI question), `supervisor <wf>` (one screen),
`status` (loop health), `audit --wf --kind` (raw decision log). The `decisions` table is append-only, enforced by
SQLite triggers.

**Page on** (each message names the workflow and the decision row to read):
- ingest lag > 30 sim-minutes after a tick, or no new chunk for > 2 ticks (the loop is blind);
- `error` decisions > 5/hour or `run.sh` restarting the controller > 3/hour (crash loop);
- credits within 10 % of the incident reserve (next incident may be unfixable);
- an approval approved but not applied after 60 min (the 2 h apply window will lapse);
- an incident open > 4 h without a fix proposal (needs a human).

**Don't page** (supervisor view / morning report): KPI drift alerts, caller-ID degraded/rotated (handled
automatically within policy), experiment winners and rollbacks, rejected or expired proposals, holds for approver
hours or fatigue. These are expected behaviour of the loop, not breakage.

Today these signals are rows in `metrics`/`decisions` readable through `status`; wiring them to a pager is
listed in §14.

## 11. Results

### public_01_dev (`reports/public_01_dev.md`)

{{P01_TABLE}}

{{P01_CHANGES}}

### public_02_incidents (`reports/public_02_incidents.md`)

{{P02_TABLE}}

{{P02_CHANGES}}

### Out of sample: the robustness suite (`reports/robustness.md`)

Two public scenarios are too few to trust, and a controller tuned to them is the failure the brief warns about.
We generated six scenarios of our own with the same schema and different truth, policies and incidents
(`scripts/make_robustness_scenarios.py`; README "Robustness suite"), and run each — plus both public scenarios —
at two random seeds. The table is the simulator grader's output:

{{ROBUST_TABLE}}

{{ROBUST_NOTES}}

### Interpretation

* **Where we helped.** Conclusion rate up on every workflow in both scenarios. The biggest contributors, from
  the audit trail: caller-ID load spreading and moving off flagged numbers (pickup +10–40 %; on
  public_02 `ks_cancel` the flagged number's share went from 50 % to 10 % on the day of the flag and 0 % after),
  cohort call-hour weights from history, and welcome/voice winners promoted with a holdout. On `pickup_rate`-primary
  `nw_kyc` the primary KPI moved most ({{KYC_PICKUP}}) with engagement inside its guardrail.
* **Incidents.** public_02's unsafe supervisor prompt on `ks_cancel` was detected by a validation probe 15 minutes
  after the edit, reverted through an approval that said so, and verified; MTTR {{P02_MTTR}} min; hallucinated
  calls {{P02_HALLUC}} vs the baseline. The supervisor's mid-experiment voice edit on `nw_renewal` was respected
  (dimension locked 48 h, experiment aborted, never overwritten).
* **Where we were harmful, and why.** {{HARM_EXPLAIN}}
* **Decay.** The decaying welcome message (`W3`) was promoted on its early lift, then rolled back: its share fell
  to 0 within {{DECAY_DAYS}} days of the decay onset. That is slower than we'd like: with a 15 % holdout the
  test needs a day of post-decay data, and the effect fades over two days before it is clearly negative.
* **Governance hygiene.** {{GOV_LINE}}
* **What we'd change next.** Faster decay detection (CUSUM on the holdout lift, larger holdout for variants
  promoted on short tests); a smaller challenger share for experiments with ≥ 3 challengers to cut launch cost;
  an interaction check before promoting a welcome × voice combination.
