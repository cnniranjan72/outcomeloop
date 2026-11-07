# OutcomeLoop — Design Decisions (living spec)

This is the engineering spec the controller is built against. `SUBMISSION.md` summarises it; this file holds
the detail and the reasoning. Every constant here lives in `src/outcomeloop/config.py` with the same name.

## 0. Ground rules we hold ourselves to

* The controller knows **only what the HTTP API returns**. No `import sim`, no reading `runs/`, no scenario
  YAML. (Test harness scripts under `scripts/` may read `runs/` *after* a run to produce evidence — they are not
  the controller.)
* No numbers in this file are tuned against public ground truth. Thresholds are derived from statistics
  (error rates, power) and from the governance policy each workflow publishes via `GET /workflows/{id}`.

## 1. Process model

One Python process, single-threaded, synchronous control loop (`outcomeloop.main`). The simulator only moves
when we call `POST /sim/advance`, so concurrency buys nothing; determinism and crash-safety buy a lot.

```
loop:
  reconcile()                  # on start-up and after any uncertain remote call
  ingest_new_chunks()          # one SQLite transaction per chunk: events + checkpoint
  handle_events()              # config_changed / approval_decided side effects
  governance_tick()            # poll pending approvals, apply approved ones, expire/lapse bookkeeping
  if decision_due: decide()    # detectors -> planner -> changeset -> proposal/auto-apply
  advance(15 min)              # always one tick: approvals have a 2h apply window, incidents need speed
```

## 2. Storage — SQLite (stdlib `sqlite3`, WAL, `synchronous=FULL`)

Why: zero new stateful infrastructure (SRE memo); a single file is trivially backed up and inspected; the
repository layer is plain SQL that ports to Postgres (which the platform already runs) without an ORM.

| Table | Purpose |
|---|---|
| `meta` | world fingerprint (scenario name + first history event hash), schema version |
| `chunks` | the checkpoint: one row per fully ingested chunk (number, events, timing) |
| `inbox` | side-effect events (`config_changed`, `approval_decided`) awaiting their handler; retried until done |
| `kv` | small JSON controller memory (bootstrap, schedule, caller-ID state, locks, blacklists, holds) |
| `codes` | string ↔ small-int dictionary for the integer-encoded call rows |
| `campaigns` | campaign id, day, size, config version at creation |
| `workflows` | static workflow description as returned by the API (JSON) |
| `persons` | person_int → packed feature code (lang, tier, age, value) |
| `leads` | lead_int → person, campaign, status (active/concluded/unreachable) |
| `calls` | one row per call event, integer-encoded; PK `(wf, minute, event_id)` WITHOUT ROWID; `INSERT OR IGNORE` |
| `config_versions` | every config version we observed (actor, dims, proposal/approval ids, full config) |
| `cohorts` | the shared cohort object: `(wf, cohort_id, where_json, created_at, rationale, status)` |
| `experiments` | experiment per (wf, dim): arms, incumbent, start version/minute, plan, status, result |
| `proposals` | our proposal intents + full request body + remote approval state (state machine below) |
| `incidents` | detector incidents (type, wf, opened/closed, evidence) |
| `credits_ledger` | every credit-spending call: intent, result, cost |
| `decisions` | **append-only audit log**: every decision incl. *no-op* decisions with evidence + reasoning |
| `metrics` | loop health samples (ingest lag, events/s, decisions/hour, credits, backlog) |

Exactly-once ingestion: a chunk's rows and the checkpoint update commit in **one transaction**. A crash
mid-chunk rolls back, and restart re-reads the chunk. `INSERT OR IGNORE` on the event PK is a second line of
defence.

## 3. Shared cohort object (C2)

* A **Cohort** is `{cohort_id, where}` with the simulator's semantics (AND across features, OR within a list).
  A workflow has one ordered **CohortSet**; membership is first-match, otherwise `default`. This set is mirrored
  1:1 into `config.cohorts`, so "cohort `age_60p`" means the same leads in detection, experiments, the
  supervisor view and the simulator's own `cohort_id` on call events (checked daily: `check_cohort_agreement` compares our assignment with the
  simulator's `cohort_id` on every call under our cohort set and alerts on any mismatch; 0 mismatches on 95k
  public_02 calls).
* **Feature slices** (`lang=ta`, `age_band=60+`, …) are *candidate generators* for heterogeneity checks; they
  are never shown as cohorts. A slice becomes a cohort only through a proposal.
* Initial CohortSet is bootstrapped from history (C3): for each feature we measure how much the hour-of-day
  pickup profile differs across its values (deviance of `pickup ~ hour × feature` vs `pickup ~ hour + feature`).
  The strongest feature(s) define schedule cohorts, subject to **minimum cohort share 10 % of dials** and **max 6
  cohorts** so traffic is not fragmented.

## 4. Detection (thresholds on populations, never single calls)

All detectors compare *concurrent randomised* groups where possible (caller-ID and variants are randomised per
dial, so hour/person mix is balanced in expectation), and use one-sided z-tests with Bonferroni-corrected
thresholds for the number of looks per day.

| Detector | Signal | Window | Minimum n | Fires when |
|---|---|---|---|---|
| Caller-ID degraded | pickup(DID) vs pooled pickup(other DIDs), and vs the DID's own previous week | rolling 6h and 24h | 300 dials on the DID | ratio < 0.85 **and** z < −3.5 **and** (if it has a week of history) > 15 % drop vs own past, z < −3 |
| Caller-ID healthy | same | 24h or 72h (since probe start for re-probes) | 150 dials | ratio − se ≥ 0.85 and not degraded |
| Hallucination spike | flag rate on current prompt vs workflow's history baseline | since the last prompt change, at most 24 h | 250 connected | rate > 1.5× baseline **and** z > 3.5 |
| KPI drift | workflow pickup / engagement, last 24h vs trailing 7d | daily | 1000 dials / 500 connected | relative drop > 5 % and z > 3 (alert only) |
| Decay | winner-vs-holdout lift, recent 24h vs lift at promotion | hourly | 120 connected per arm (window widened 24→72 h until reached) | z < −2.33 vs promotion LCB80, or recent lift < 0 with z < −2.33; window 24→72h until ≥ 120 connected |

z = 3.5 one-sided ≈ 2.3e-4 per look; decisions run hourly (~12–24 looks/day), so ≲0.5 % false alarms per workflow-day, and a flags-only alarm
still needs validation to confirm (§8).

## 5. Experiments (C6) — welcome_message × voice

* **Factorial**: both dimensions are randomised independently per dial, so each dimension's arms are compared
  on all traffic (marginal analysis). Before promotion a winner must also beat the
  incumbent within the other dimension's dominant option (`_interaction`), so a winner that only wins next to a
  minor option is blocked; a full interaction model is not fitted.
* **Allocation**: incumbent keeps `1 − s`, challengers split `s = 0.40` evenly. (Dunnett's √k rule would give
  ~0.6 to challengers; we trade power for bounded harm — see compliance memo.)
* **Decision metric**: engagement, always — welcome and voice are heard only after connect, so they cannot move
  pickup; on pickup-primary workflows this improves the guardrail KPI and the business outcome. **Guardrail**: the other KPI must not drop by more than the policy margin;
  we read `*_max_drop` as an **absolute** drop in the rate (0.02 = 2 percentage points). A change is blocked
  when the point estimate of the drop exceeds the margin, or when the drop is statistically significant
  (z > 1.645) and exceeds half the margin (assumption A-guardrail).
* **Sample size**: `N` per arm for MDE 10 % relative, α = 0.05 one-sided family-wise, power 0.8, at the
  baseline rate from history. Max duration 5 days: `N_plan = min(N_mde, connected calls the arm can collect in 5 days)`; the achieved MDE
  at `N_plan` is recorded in the experiment row and the proposal, so a short test is visibly under-powered.
  At the horizon the incumbent is retained ("no evidence → no change").
* **Sequential looks**: Lan-DeMets O'Brien-Fleming spending `α(t) = 2 − 2Φ(z_{α/2}/√t)` with information fraction
  `t = n/N`; nominal level at each look = increment of spent α (Bonferroni over looks → conservative, valid).
* **Multiple comparisons**: Holm across challengers within a dimension at 80 % of the look's α; cohort-level
  winners (Bonferroni over cohorts) at the other 20 %; separate α for each dimension.
* **Harm stopping**: a challenger significantly worse than the incumbent is dropped — hourly at z < −2.33 (repeated
  check), at a daily look at z < −1.645, both with ≥ 200 connected; it is blacklisted for 14 days; dropping an arm only moves traffic back to the incumbent.
* **Cohort harm check**: before promoting, the winner is tested in every cohort of the CohortSet; a cohort where
  the winner is worse with z < −1.645 keeps the incumbent (per-cohort allocation), because "an improvement that
  hurts a cohort is worth less than nothing" (CTO).
* **Promotion**: winner gets `1 − h`, previous incumbent keeps a **holdout h = 0.15** for decay detection.
* **Evidence integrity**: stats come from call events' actual `variant` field, restricted to calls dialled under
  config versions belonging to the experiment. An arm that never ran has n = 0 and cannot win.
* **Determinism**: given the same events, the same decision is produced (no RNG in decisions; ties broken by
  option order).

## 6. Caller-ID (C5)

Target allocation = equal split over DIDs classified **healthy**, 0 for **degraded**, a 5 % probe (10 % total budget) for untested
DIDs, 2 % for a degraded DID being re-probed after its rest (24 h, doubling). A DID whose health is still
**unknown keeps the share it has**: insufficient evidence never moves traffic (this matters on
`next_campaign_only` workflows, where an allocation reaches traffic a campaign later). Equal split minimises
per-number volume, the standard defence against carrier spam-flagging. "Degraded" needs both a relative drop
vs the other numbers and, when the number has its own history, a drop vs that history, so steady volume fatigue
next to a fresh number is not mistaken for a spam flag (found via the crash-recovery comparison run).

## 7. Call-time (C3/C4) — cohort level

`hour_weights[cohort][h] = clip((p̂(cohort,h)/p̄(cohort))^γ, 0.25, 4)` with γ = 2, using smoothed (empirical
Bayes toward the workflow hour profile) pickup estimates from history. Never 0 (a 0 can strand capacity).
Dry run = historical re-weighting estimate of pickup holding per-hour dial volume fixed (ignores pool depletion
— stated in the proposal). Per-person `lead_preferred_hour` is **not rolled out blindly** (thin per-person evidence; 0.25×
penalty outside the preferred hour makes errors expensive): it runs as a randomised, self-terminating experiment
(`persontime.py`) and stays only on evidence.

## 8. Incidents — hallucination (C8)

1. Detector fires (or a supervisor changes `prompt_version` → validation probe of the new prompt, 3 credits; 1 when
   credits are scarce, from 4 credits). A new prompt must *demonstrate* it clears the approver's gate (exact 95 %
   upper bound on its failure rate ≤ 1 − `min_validation_pass_rate`, `stats.validation_vetoes`): below the gate →
   incident; passing only on the point estimate → a pooled second run (credits ≥ 30); still not shown → incident.
   A flag-triggered incident needs a confirming validation; for a prompt changed in the last 3 days it vetoes only
   with the same 95 % bound, for the long-standing reference prompt with threshold + 1 SE.
2. Candidates: prompts from our own history with ≥ 1000 connected calls and a flag rate ≤ 1.25× the reference,
   ordered by observed engagement (validation measures safety only),
   first; LLM `suggest-fixes` only if no known-good candidate passes validation (CTO: no compute that
   doesn't change a decision).
3. Validate each candidate (`n = 300`, fewer when credits are scarce). Deterministic choice: passes policy threshold, then prefers
   observed engagement evidence, then higher pass rate.
4. Propose through `/approvals` with `evidence.validation_run_id` (prompt changes are never auto-applicable).
   A supervisor's edit is reverted **only** through an approval that says so in the summary.
5. Verify after apply: flag rate back under 1.5× baseline and engagement not below guardrail; else re-open.

Credit policy: an **incident reserve of 40 %** of the starting budget is untouchable by non-incident work.

## 9. Governance (C9)

Proposal state machine (ours):

```
SUBMITTING → PENDING → APPROVED → APPLYING → APPLIED      (post-apply verification and rollback are decisions,
                                                          not proposal states)
                 ↘ SUBMIT_FAILED      ↘ REJECTED | EXPIRED      ↘ LAPSED | STALE → (re-plan)
AUTO: AUTO_APPLYING → APPLIED | AUTO_DENIED | AUTO_FAILED;  PENDING/APPROVED → WITHDRAWN
```

* **One open proposal per workflow.** New wants accumulate into the next batched changeset.
* **Timing**: submit only when the *worst-case* decision time (`next_working(now + latency_max)`) falls before
  `expires_at`, inside approver hours, and after tenant preferences (Kestrel: not before 11:00).
* **Fatigue**: trailing-24h count of *all* our requests (rejected and expired count too, as the approver counts them) < `min(policy max, tenant preference)`; one slot is reserved for incidents.
* **Stale base**: on 409 at submit or apply → rebase the *changeset* (dim-level patches) on the current config;
  drop patches touching dims a supervisor changed in the last 48h; re-propose with a new id.
* **Expired = rejected** (Product): re-plan from fresh data next cycle, never resubmit the old body.
* **Auto-apply** only for operational dims (caller_id, schedule) and only where policy allows; within
  `max_shift`. Customer-facing dims (welcome, voice, prompt) **always** go through approval, even where the
  policy would allow auto-apply (Kestrel's supervisor asked to be told first; Northwind compliance requires it).
  Ramps larger than `max_shift` are split into steps ≥ 1 h apart, each re-checked, cumulative ≤ 3×max_shift/day.
* **Crash safety**: the proposal row (with its deterministic id and full body) is committed *before* the HTTP
  call. Restart reconciles `SUBMITTING`/`APPLYING` rows against `GET /approvals` and `/config/history` before any
  retry. A timeout is never treated as failure.

## 10. Audit (C12)

Every decision row: `decision_id, ts (sim), wf, kind, actor, inputs/evidence JSON, reasoning text,
outcome, links (proposal_id, approval_id, config_version, experiment_id, incident_id)`. CLI:
`python -m outcomeloop why <wf> --at "D3 14:00"` joins config version → proposal → approval → evidence → what
happened after (post-apply verification decisions).

## 11. Impact score, affected leads, dry run (C10)

* `impact_score = clip(lift_lcb / 0.10, 0, 1) × (1 − holdout share)` for a promotion, where `lift_lcb` is the 80 % lower confidence
  bound of the relative primary-KPI lift from the dry run (0 for pure exploration). Exploration proposals carry a
  fixed 0.15 (`learning`), validated incident fixes 0.9. All components are shown in the proposal so the
  supervisor's queue ranking is explainable.
* `affected_leads` = active (not concluded, inside cadence) leads in the workflow (an upper bound when only some
  cohorts change); for
  `next_campaign_only` workflows, customer-facing changes count the next campaign's expected size instead.
* `dry_run` replays our own call history: variant changes use observed per-arm, per-cohort rates; schedule uses
  historical re-weighting at fixed per-hour volume; caller-ID uses per-DID pickup; prompts use validation runs
  and the prompt's observed flag rate. Every dry run states its window, n and known biases.
