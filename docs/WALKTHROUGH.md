# Walkthrough: one decision, end to end, from the audit store

This tour uses ten commands to rebuild one real decision from OutcomeLoop's own SQLite store, without the
simulator. The decision: on public_02, at **D3 13:30**, `ks_cancel` was changed back from prompt `P2` to `P1`.
We cover why, who approved it, and what happened next.

**Where the output comes from.** Every block below is real output, trimmed only where marked `…`. It was
captured from `state/public_02_incidents.db` and `state/public_01_dev.db` produced by `scripts/run_scenario.sh`
during development, a few commits before the final run. Re-running a scenario rebuilds the store, so your ids
and minutes will differ slightly from the blocks below and from `reports/`. In the final committed public_02 run,
for example, the same revert is `ol-ks_cancel-5025-14`, approved and applied at D3 12:30. The decision chain is
identical: supervisor edit → validation probe → incident → known-good fix validated → approval → apply → verify.

Older captures show `—` mis-encoded as `â€”` in some summaries. That defect was fixed before the final run.

Setup:

```bash
cd outcomeloop
export PYTHONPATH=src PYTHONUTF8=1
```

---

## 1. Is the loop healthy, and is there anything to look at?

```bash
python -m outcomeloop --db state/public_02_incidents.db status
```

```
# OutcomeLoop status at D9 21:00

events ingested: 324342 in 16.5s (19,600 events/s while ingesting)
ingest lag: 180.0 sim-minutes · credits remaining: 194.0 · open proposals: 0.0 · peak RSS: 0.0 MB
wall seconds per sim day: 0:5s, 1:4s, 2:5s, 3:5s, 4:5s, 5:5s, 6:5s, 7:5s, 8:5s, 9:5s

## Recent alerts / incidents
  D5 21:00 wf0 decay_detected: welcome_message: winner stopped winning in ['default'] â€” rolling back to incumbent
  D3 11:45 wf2 incident_opened: hallucination incident on prompt P2

## Proposals by state
  APPLIED: 20
  REJECTED: 3

## Decisions by kind
  experiment_look: 22
  config_changed: 22
  hold: 20
  …
  incident_verified: 1
  incident_opened: 1
  incident_fix_selected: 1
  incident_fix_applied: 1
  …
  controller_start: 1
  controller_finish: 1
```

What to notice:

- There is one hallucination incident, on `wf2` (`ks_cancel`), and one decay rollback.
- 6 credits were spent (200 → 194).
- Nothing is left in an uncertain proposal state.
- The ingest lag of 180 at D9 21:00 is the overnight gap: no chunks arrive outside dialling windows.
- `peak RSS: 0.0 MB` is the known Windows metric defect (README › Observability).

## 2. What did the controller do on `ks_cancel` around D3?

```bash
python -m outcomeloop --db state/public_02_incidents.db audit --wf ks_cancel --limit 200
```

```
…
D3 11:00  ks_cancel    experiment_look          controller welcome_message: look t=0.684 â€” continue
D3 11:00  ks_cancel    experiment_look          controller voice: look t=0.622 â€” continue
D3 11:30  ks_cancel    config_changed           supervisor v8 by supervisor: prompt_version
D3 11:30  ks_cancel    supervisor_edit          controller supervisor changed ['prompt_version']; locked for 48h â€” we will not propose changes to these dims
D3 11:45  ks_cancel    validation_run           controller validated P2: pass_rate 0.937 (n=300, 3 credits) â€” probe supervisor prompt change v8
D3 11:45  ks_cancel    incident_opened          controller hallucination incident on prompt P2
D3 11:45  ks_cancel    validation_run           controller validated P1: pass_rate 0.990 (n=300, 3 credits) â€” candidate fix for inc-ks_cancel-5025 (known_good)
D3 11:45  ks_cancel    incident_fix_selected    controller inc-ks_cancel-5025: fix = prompt P1 (known_good), validation pass 0.990 >= 0.97
D3 11:45  ks_cancel    proposal_submitted       controller ol-ks_cancel-5025-15 -> PENDING: revert unsafe prompt P2 -> P1
D3 12:00  ks_cancel    did_health               controller caller ID D2: degraded -> probe
D3 13:13  ks_cancel    approval_decided         approver   apr_00008 approved
D3 13:30  ks_cancel    proposal_approved        controller ol-ks_cancel-5025-15: approved by client approver
D3 13:30  ks_cancel    proposal_applied         controller ol-ks_cancel-5025-15: applied
D3 13:30  ks_cancel    config_changed           controller_approved v9 by controller_approved: prompt_version
D3 13:30  ks_cancel    incident_fix_applied     controller inc-ks_cancel-5025: prompt P1 live (v9)
D3 18:00  ks_cancel    incident_verified        controller inc-ks_cancel-5025: after fix flag rate 0.0141 vs ref 0.0137 on 426 connected calls
…
```

What happened, step by step:

1. **11:30.** A supervisor shipped `P2`. The controller did not overwrite it. It locked `prompt_version` for 48 h
   against routine changes and marked the workflow urgent.
2. **11:45, the next tick.** A validation probe of `P2` returned 0.937, below the policy's 0.97. That opened an
   incident. This took 15 minutes, before enough real calls existed for the flag-rate detector.
3. **The fix.** The first known-good candidate `P1` validated at 0.990. A prompt-only approval request went out
   at 11:45. This is inside Kestrel's preferred window: `not_before_hour` 11 from `config/tenant_preferences.json`.
4. **Approval and apply.** The approver approved at 13:13. Our next poll (13:30) applied it.
5. **Verification.** The fix was verified at 18:00.

The grader scored this incident in `reports/public_02_incidents.md` › Incidents.

## 3. Ask the review question at 13:00: what was live then, and why?

```bash
python -m outcomeloop --db state/public_02_incidents.db why ks_cancel --at "D3 13:00"
```

```
# why: ks_cancel at D3 13:00

Config v8 became live at D3 11:30 — actor: supervisor, changed: ["prompt_version"]
This was a client supervisor edit (bypasses governance). Our reaction:
  D3 11:30  supervisor_edit          supervisor changed ['prompt_version']; locked for 48h â€” we will not propose changes to these dims
  D3 11:45  validation_run           validated P2: pass_rate 0.937 (n=300, 3 credits) â€” probe supervisor prompt change v8
  D3 11:45  incident_opened          hallucination incident on prompt P2
  D3 11:45  validation_run           validated P1: pass_rate 0.990 (n=300, 3 credits) â€” candidate fix for inc-ks_cancel-5025 (known_good)
  D3 11:45  incident_fix_selected    inc-ks_cancel-5025: fix = prompt P1 (known_good), validation pass 0.990 >= 0.97
  D3 11:45  proposal_submitted       ol-ks_cancel-5025-15 -> PENDING: revert unsafe prompt P2 -> P1
```

At 13:00 the supervisor's version was still live and our fix was waiting for the approver. `why` takes the
version in force at T and, for a supervisor version, lists our reactions in the following 6 h.

## 4. Which evidence did the prompt decision rest on, and what did it cost?

```bash
python -m outcomeloop --db state/public_02_incidents.db audit --wf ks_cancel --kind validation_run
sqlite3 -header state/public_02_incidents.db "SELECT id, minute, wf, kind, purpose, state, cost FROM credits_ledger"
```

```
D3 11:45  ks_cancel    validation_run           controller validated P2: pass_rate 0.937 (n=300, 3 credits) â€” probe supervisor prompt change v8
D3 11:45  ks_cancel    validation_run           controller validated P1: pass_rate 0.990 (n=300, 3 credits) â€” candidate fix for inc-ks_cancel-5025 (known_good)
```

```
id|minute|wf|kind|purpose|state|cost
1|5025|2|validation|probe supervisor prompt change v8|done|3.0
2|5025|2|validation|candidate fix for inc-ks_cancel-5025 (known_good)|done|3.0
```

The whole incident cost two validation runs (6 credits) and no LLM call. A known-good prompt from our own
history validated first, so `/llm/suggest-fixes` was never needed. Every ledger row is `done`, which means
nothing was left in flight. Minute 5025 is D3 11:45 (3 × 1440 + 705).

## 5. The change itself: who approved it, what was sent, what happened next

```bash
python -m outcomeloop --db state/public_02_incidents.db why ks_cancel --at "D3 13:30"
```

```
# why: ks_cancel at D3 13:30

Config v9 became live at D3 13:30 — actor: controller_approved, changed: ["prompt_version"]

## Proposal ol-ks_cancel-5025-15 (approval route, incident), created D3 11:45, state APPLIED
Approved by: client approver, approval apr_00008 (decided 2027-01-07T13:13:00+05:30, created 2027-01-07T11:45:00+05:30)
Summary: revert unsafe prompt P2 -> P1
Impact score: 0.9 · affected leads: 3657
Rationale: Safety incident inc-ks_cancel-5025: the live prompt is producing hallucinations above the workflow's own baseline. revert unsafe prompt P2 -> P1; validation run val_00002 passed at 0.99. This reverses a recent prompt change and is sent for your appr…
Diff: {"prompt_version": {"after": "P1", "before": "P2"}}

## Decisions that led to it
  D0 18:00  did_health               caller ID D3: unknown -> healthy
  …
  D3 11:30  supervisor_edit          supervisor changed ['prompt_version']; locked for 48h â€” we will not propose changes to these dims
  D3 11:45  validation_run           validated P2: pass_rate 0.937 (n=300, 3 credits) â€” probe supervisor prompt change v8
  D3 11:45  incident_opened          hallucination incident on prompt P2
  D3 11:45  validation_run           validated P1: pass_rate 0.990 (n=300, 3 credits) â€” candidate fix for inc-ks_cancel-5025 (known_good)
  D3 11:45  incident_fix_selected    inc-ks_cancel-5025: fix = prompt P1 (known_good), validation pass 0.990 >= 0.97
  D3 11:45  proposal_submitted       ol-ks_cancel-5025-15 -> PENDING: revert unsafe prompt P2 -> P1
  D3 12:00  did_health               caller ID D2: degraded -> probe
  D3 13:30  proposal_approved        ol-ks_cancel-5025-15: approved by client approver

## What happened next (48h)
  D3 18:00  incident_verified        inc-ks_cancel-5025: after fix flag rate 0.0141 vs ref 0.0137 on 426 connected calls
  D4 11:00  experiment_look          welcome_message: look t=0.913 â€” continue
  D4 11:00  experiment_winner        voice: winner V3 (look t=0.843, alpha_look=0.0187)
  D4 12:00  did_health               caller ID D2: probe -> degraded
  D4 12:00  proposal_submitted       ol-ks_cancel-6480-17 -> PENDING: voice: promoting default=V1 15%,V3 85%
  D4 14:15  proposal_approved        ol-ks_cancel-6480-17: approved by client approver
  D4 14:15  proposal_applied         ol-ks_cancel-6480-17: applied
  D4 14:15  config_changed           v10 by controller_approved: voice
  D4 14:15  experiment_promoted      voice experiment promoted (v10)
  …

KPIs 24h before → 24h after:
  pickup 0.260 → 0.252   engagement 0.486 → 0.502   (dials 4800 → 4800)
```

This one screen answers the review question:

- **Who approved:** approval `apr_00008`, decided 13:13. The API does not expose the approver's name.
- **What was sent:** a prompt-only diff with validation run `val_00002`, impact score 0.9 and 3,657 affected leads.
- **What happened next:** verification at 18:00, and then the experiments carried on.

The supervisor's 48 h lock did not block the fix. A safety revert is the one exception, and it goes through an
approval request that says so in its rationale.

## 6. The proposal rows: intent, state, base version

```bash
sqlite3 -header state/public_02_incidents.db "SELECT proposal_id, route, state, kind, base_version, approval_id, applied_version, created_minute, updated_minute FROM proposals WHERE wf=2"
```

```
proposal_id|route|state|kind|base_version|approval_id|applied_version|created_minute|updated_minute
ol-ks_cancel-0-2|auto|APPLIED|operational|1||2|0|0
ol-ks_cancel-660-5|approval|APPLIED|routine|2|apr_00003|3|660|735
ol-ks_cancel-1080-6|auto|APPLIED|operational|3||4|1080|1080
ol-ks_cancel-1140-8|auto|APPLIED|operational|4||5|1140|1140
ol-ks_cancel-3600-11|auto|APPLIED|urgent|5||6|3600|3600
ol-ks_cancel-3660-12|auto|APPLIED|urgent|6||7|3660|3660
ol-ks_cancel-5025-15|approval|APPLIED|incident|8|apr_00008|9|5025|5130
ol-ks_cancel-6480-17|approval|APPLIED|routine|9|apr_00010|10|6480|6615
ol-ks_cancel-7920-18|approval|APPLIED|routine|10|apr_00011|11|7920|7980
```

How to read it:

- **`base_version` 8.** The incident proposal was built on the supervisor's version, so it applied cleanly. Had
  the supervisor edited again before 13:30, `_apply` would have seen a different live version, marked the row
  `STALE` and re-planned instead of forcing it.
- **The `urgent` auto rows at minutes 3600 and 3660 (D2 12:00 and 13:00).** These are the spam-flagged caller ID
  `D2` being ramped out under `max_shift` 0.2, in two steps one hour apart.
- **Request rate.** On `ks_cancel` this run sent at most one approval request per trailing 24 h. The tenant
  preference allows 2, and one of those is reserved for incidents.

## 7. What did one customer hear, and why?

```bash
python -m outcomeloop --db state/public_02_incidents.db customer ks_cancel:p0011842 --day 3
```

```
# calls to ks_cancel:p0011842 on D3
D3 11:44 cohort=age_31_45 heard welcome=W1 voice=V4 prompt=P2 from D3 | connected=True engaged=False | config v8 set by supervisor (proposal None, approval None)
D3 13:43 cohort=age_31_45 heard welcome=W1 voice=V1 prompt=P1 from D3 | connected=False engaged=False | config v9 set by controller_approved (proposal ol-ks_cancel-5025-15, approval apr_00008)
Run `why <workflow> --at <time>` on any config version above for the reasoning and approver.
```

This is the Compliance (IRDAI) question: down to the variant, the config version and the proposal and approval
that made it live. This person heard the supervisor's `P2` at 11:44, and our approved `P1` at 13:43. `V4` vs
`V1` is the voice experiment's randomisation.

## 8. The client supervisor's one screen

```bash
python -m outcomeloop --db state/public_02_incidents.db supervisor ks_cancel
```

```
# ks_cancel — supervisor view at D9 21:00

Live config v11 (by controller_approved): prompt P1, default welcome_message={'W1': 0.15, 'W2': 0.85}, voice={'V1': 0.15, 'V3': 0.85}, caller_id={'D1': 0.5, 'D3': 0.5}
Last 24h: 4800 dials · pickup 23.8% · engagement 54.3% (separate KPIs, never blended)

## Cohorts (shared definition used everywhere)
  age_18_30      {"age_band":["18-30"]}  [live]
  age_31_45      {"age_band":["31-45"]}  [live]
  age_46_60      {"age_band":["46-60"]}  [live]
  age_60p        {"age_band":["60+"]}  [live]

## Being tested / winning
  welcome_message  promoted     arms ['W1', 'W2', 'W3'] incumbent W1 → winner W2 | lifts W2 +9.7% (z 2.84), W3 +0.8% (z 0.24)
  voice            promoted     arms ['V1', 'V2', 'V3', 'V4'] incumbent V1 → winner V3 | lifts V2 +5.5% (z 1.25), V3 +11.8% (z 2.64), V4 -5.4% (z -1.21)

## Waiting for you
  nothing

## Changed today

## Open incidents
  none
```

The cohorts listed here are the same `cohort_id`s that appear on call rows (step 7, `cohort=age_31_45`) and in
the experiment's cohort checks (step 9). There is one definition. The 15 % holdouts (`W1`, `V1`) are visible in
the live config.

## 9. Why V3 won: the statistics behind one `experiment_winner`

```bash
sqlite3 state/public_02_incidents.db "SELECT evidence FROM decisions WHERE wf=2 AND kind='experiment_winner' AND summary LIKE 'voice%'"
```

```
{"action":"promote","alpha_look":0.0187,
 "arms":{"V2":{"connected":683,"dials":2573,"eng_rate":0.5154,"engaged":352,"lift_rel":0.0547,"p":0.105,"pickup_diff":0.0113,"pickup_z":1.17,"z":1.25},
         "V3":{"connected":635,"dials":2537,"eng_rate":0.5465,"engaged":347,"lift_rel":0.1183,"p":0.00413,"pickup_diff":-0.0038,"pickup_z":-0.4,"z":2.64},
         "V4":{"connected":651,"dials":2501,"eng_rate":0.4624,"engaged":301,"lift_rel":-0.0538,"p":0.887,"pickup_diff":0.0062,"pickup_z":0.64,"z":-1.21}},
 "cohort_check":{"age_18_30":{"inc_conn":749,"keeps_incumbent":false,"lift_rel":0.1058,"win_conn":171,"z":1.02},
                 "age_31_45":{"inc_conn":940,"keeps_incumbent":false,"lift_rel":0.1209,"win_conn":214,"z":1.65},
                 "age_46_60":{"inc_conn":713,"keeps_incumbent":false,"lift_rel":0.1315,"win_conn":161,"z":1.55},
                 "age_60p":{"inc_conn":416,"keeps_incumbent":false,"lift_rel":0.1168,"win_conn":89,"z":1.11}},
 "guardrail_blocked":[],"horizon":false,
 "incumbent":{"connected":2818,"dials":11089,"eng_rate":0.4886,"engaged":1377,"option":"V1"},
 "label":"D4 11:00","minute":6420,"n_plan":779,"significant":["V3"],
 "stability":{"V3":{"recent_conn":157,"recent_inc_conn":711,"recent_lift":0.0916,"unstable":false,"z_vs_overall":0.69}},
 "t":0.843,"winner":"V3"}
```

(The output is one line. Line breaks were added for reading.)

How the rules apply to these numbers:

- **The look.** At information fraction `t = 0.843` the O'Brien-Fleming budget allowed `alpha_look = 0.0187` for
  this look.
- **Holm.** Holm across the three challengers rejected only for `V3`: p = 0.00413 ≤ 0.0187 / 3.
- **Guardrail.** Pickup moved by −0.0038, which is inside the 0.02 margin, so nothing was blocked.
- **Stability.** The last-24h lift (+0.092) is positive and not significantly below the whole-window lift.
- **Cohort harm check.** No cohort was significantly hurt, so no cohort keeps `V1` through a per-cohort
  allocation.

Promotion went out the next hour (D4 12:00, step 5's "what happened next"). It waited for the hour because
11:00 was blocked by fatigue: `hold` at D4 11:00, `fatigue: 1/2 used, last slot reserved for incidents`. The
incident request from D3 11:45 aged out of the 24 h window at 11:45.

## 10. Decay and rollback on another workflow (public_01)

```bash
python -m outcomeloop --db state/public_01_dev.db why nw_renewal --at "D5 15:00"
```

```
# why: nw_renewal at D5 15:00

Config v7 became live at D5 15:00 — actor: controller_approved, changed: ["welcome_message"]

## Proposal ol-nw_renewal-7860-18 (approval route, urgent), created D5 11:00, state APPLIED
Approved by: client approver, approval apr_00010 (decided 2027-01-09T14:34:00+05:30, created 2027-01-09T11:00:00+05:30)
Summary: welcome_message: rolling_back default=W1 100%
Impact score: 0.6 · affected leads: 2490
Rationale: welcome_message: the promoted option stopped beating the holdout â€” roll back.
Diff: {"welcome_message": {"default": {"after": {"W1": 1.0}, "before": {"W1": 0.15, "W3": 0.85}}}}

## Decisions that led to it
  D3 10:00  did_health               caller ID D4: probe -> degraded
  D3 10:00  experiment_winner        welcome_message: winner W3 (look t=0.606, alpha_look=0.0104)
  D3 10:00  proposal_submitted       ol-nw_renewal-4920-13 -> PENDING: welcome_message: promoting default=W1 15%,W3 85%
  D3 13:30  proposal_approved        ol-nw_renewal-4920-13: approved by client approver
  D5 10:00  did_health               caller ID D4: degraded -> probe
  D5 11:00  decay_detected           welcome_message: winner stopped winning in ['default'] â€” rolling back to incumbent
  D5 11:00  proposal_submitted       ol-nw_renewal-7860-18 -> PENDING: welcome_message: rolling_back default=W1 100%
  D5 15:00  proposal_approved        ol-nw_renewal-7860-18: approved by client approver

## What happened next (48h)
  …
  D6 15:00  experiment_designed      welcome_message: test ['W1', 'W2'] (incumbent W1 keeps 60%)
  D6 15:00  proposal_submitted       ol-nw_renewal-9540-19 -> PENDING: welcome_message: designed default=W1 60%,W2 40%
  …

KPIs 24h before → 24h after:
  pickup 0.282 → 0.281   engagement 0.525 → 0.551   (dials 3600 → 3600)
```

This is the full C7 loop:

1. `W3` won on D3 and was promoted with a 15 % holdout on `W1`.
2. On D5 the winner-vs-holdout lift fell significantly below the promotion's 80 % lower confidence bound.
3. A rollback request went out the same hour as an `urgent` proposal, which may use the reserved slot.
4. After the rollback was applied, the next welcome test excluded `W3`, which is blacklisted for 7 days.

To see the decay statistics, use the matching evidence query on public_02, where the same variant decayed:

```bash
sqlite3 state/public_02_incidents.db "SELECT evidence FROM decisions WHERE kind='decay_detected'"
```

```
{"decayed":["default"],"scopes":{"default":{"holdout_connected":173,"lift_at_promotion":0.085,"lift_now":-0.0656,"promotion_lcb80":0.0648,"winner_connected":917,"z_now":-1.59,"z_vs_promotion":-2.74}},"window_start":7020}
```

The lift at promotion was +0.085, with an 80 % LCB of +0.065. Now the lift is −0.066. The z against the LCB is
−2.74, below the −2.33 threshold, so the scope is decayed. Comparing against the LCB rather than the +0.085
point estimate is the winner's-curse correction.

---

**What this tour showed.** For the decision a reviewer is most likely to pick (a change to a live client's
agent), the store holds:

- the trigger and the evidence for it;
- the alternatives considered and their cost;
- the exact request sent, the approval and when it was applied;
- what each customer heard;
- the verification that followed.

None of it needs the simulator's logs.
