# Review guide — the 60-minute session

The brief says the review will (1) pick one decision the controller made on a hidden scenario and ask us to
explain it from our audit store, live; (2) change a constraint and ask what breaks; (3) ask about what we cut.
This page is the rehearsal sheet for those three, plus the questions a senior reviewer is likely to push on.
Every answer points at code or evidence in this repo.

---

## 1. Explaining any decision live (from our store, never the simulator's logs)

The controller writes one row per decision to the append-only `decisions` table. Everything below reads only
that store (`OUTCOMELOOP_DB`, or `--db`).

```bash
export PYTHONPATH=src
DB=state/outcomeloop.db                     # whatever OUTCOMELOOP_DB the hidden run used

# 1. what changed, when, by whom
python -m outcomeloop --db $DB audit --wf <wf> --kind config_changed

# 2. the full story of one change: proposal, approver, rationale, diff, the decisions that led to it, what happened next
python -m outcomeloop --db $DB why <wf> --at "D3 14:00"

# 3. the statistics behind an experiment decision (evidence JSON: arms, n, z, alpha_look, stability, cohort check)
sqlite3 $DB "select minute, summary, evidence from decisions where kind in ('experiment_winner','experiment_no_winner','decay_detected') and wf=(select wf from workflows where workflow_id='<wf>')"

# 4. what one customer heard and why (Compliance's IRDAI question)
python -m outcomeloop --db $DB customer <wf>:p0001234 --day 3

# 5. one screen for the supervisor; loop health; paging rules
python -m outcomeloop --db $DB supervisor <wf>
python -m outcomeloop --db $DB status
python -m outcomeloop --db $DB alerts
```

**How to narrate a decision** (the order the `why` output follows):
1. *Trigger* — which detector or experiment look produced it (`did_health`, `incident_opened`, `experiment_winner`,
   `decay_detected`), with its evidence numbers.
2. *Rule* — the threshold it crossed and why that threshold (`config.py` has every constant with its reason).
3. *Route* — approval or auto-apply, and why (policy `allowed_dims`, customer-facing dims always via approval).
4. *Governance* — submit time vs approver hours, fatigue slot used, approval id, decided-at, applied version.
5. *Outcome* — post-apply decisions in the next 48 h and the KPI before/after printed at the end of `why`.

If a hidden run made a decision that looks wrong, say so: the store shows the evidence it had at the time, and
that is the honest basis for "was the rule wrong, or was the data noisy?".

---

## 2. "We change a constraint — what breaks?"

| Change | What happens in our controller | Where |
|---|---|---|
| `max_requests_per_24h` → 1 | Fatigue cap = 1, no incident reserve possible (`routine_cap = cap` when cap < 2): routine changes and incidents compete for one slot per day. Routine work slows to one batched change/day; an incident on a day already used waits until the slot frees. Nothing violates the cap. | `governance.can_request` |
| Approver hours shrink (e.g. 12–14) | Submit window tightens: routine requests only if the worst-case decision lands before expiry; emergencies need the best case. Expect more `hold` decisions and slower experiments; no request is ever sent outside hours. | `governance.submit_window` |
| TTL shorter than approver latency | Routine requests are never sent (worst case can't beat expiry); emergencies still go if the best case can. We'd surface this as a standing `hold` reason; it's a policy problem to raise with the client. | `submit_window` |
| `apply_window_hours` → 0.25 | We poll every 15 sim-minutes and apply on the first tick after approval, so most approvals still apply; one decided just after a poll could lapse. Fix if needed: poll pending approvals at the decision time (`decide_at` isn't exposed; we'd poll every tick, which we already do). | `governance.tick` |
| Auto-apply enabled for `prompt_version` | We still would not auto-apply prompts: customer-facing dims (`welcome_message`, `voice`, `prompt_version`) always go through approval by our own rule (`customer_facing_dims`). Changing that is one config line, and a conversation with the client first. | `config.customer_facing_dims`, `controller.route` |
| `max_shift` → 0.05 | Caller-ID moves ramp in ≤ 0.05 steps ≥ 1 h apart, capped at 3×max_shift/day: leaving a flagged number takes ~10 h instead of 2–3. Everything else is approval-routed anyway. | `controller._auto_step` |
| `mid_flight: next_campaign_only` everywhere | Changes reach only new campaigns; experiments analyse each call's own `config_version` so stats stay valid; caller-ID "unknown keeps its share" prevents flip-flops; decay uses older campaigns' concurrent calls. Everything is slower by up to one campaign length. | `experiments.arm_counts`, `did_target` |
| Credits cut to ~10 | Validation sample size drops to 100 (1 credit); the supervisor-prompt probe is skipped below 10 credits; known-good prompts are tried before the LLM. One incident costs 1–2 credits. Suite scenario r5 tests 12 credits. | `controller._validation_n`, `_find_fix` |
| Guardrail margin → 0.005 | More winners blocked at promotion (point drop > margin, or significant drop > margin/2). Pickup cannot actually move with welcome/voice, so in practice few are blocked; on a pickup-primary workflow the engagement guardrail binds more often. | `experiments.look` |
| 10× workflows (120) | Ingest ~3 min/sim-day (measured rate); decisions scale with workflows × rows scanned: still within a 15-min tick but no longer comfortable. First fix: rollups at ingest; then shard workflows across processes. | SUBMISSION §8 |
| Hallucination rate of a "safe" prompt rises over time | The flag detector compares the live prompt with the workflow's history reference; a sustained 2× rate at z ≥ 5 opens an incident even if validation passes. | `detectors.halluc_spike`, `detect_halluc` |
| A supervisor edits caller ID / cohorts | That dimension is locked 48 h; our open proposal on the old base is found stale at apply time and re-planned without it. Our cohort set is only written when the live config has none or exactly ours. | `_on_config_changed`, `desired_config` |
| The simulator restarts mid-run | A new world: the fingerprint (scenario name + first history chunk + clock) differs, the old DB is archived and we start clean. | `controller._prepare_db` |

---

## 3. "Tell us about what you cut" — and why

| Cut / partial | Why | What it would take |
|---|---|---|
| Per-person call time (C4) | A returning person has a handful of past dials at ~30 % pickup; `lead_preferred_hour` gives 0.25× weight outside the preferred hour, so a wrong guess actively hurts that lead. Cohort-level weights from history capture the age-driven time-of-day signal (G²/df 4.6–8.2 for age vs ≤ 2 for other features). | Per-person preference only for people with ≥ 3 connects in a consistent band, A/B'd against cohort weights. |
| Fair share across tenants (C15) | Public scenarios used ~0–10 % of credits; fatigue is already per workflow. Fair-share without contention data is guesswork. | Per-tenant credit/request budgets, priority by impact score. |
| Bandit allocation | Every allocation change costs an approval (1–2/day); a bandit needs frequent re-allocation and its false-winner rate under optional stopping isn't controlled by default. | Possible on auto-apply-permitted operational dims (caller ID already behaves like a constrained bandit). |
| Welcome × voice interaction check | Marginal analysis is valid for each dimension's average effect; a strong interaction could mislead. Data is stored. | 2-way cell test before promoting a combination. |
| Cohort refinement (e.g. add `lang=ta`) | Cohorts change via approval and re-mapping the schedule; with our data volumes a slice-specific effect rarely reaches significance inside a scenario. | Slice search with Bonferroni over slices, proposal to refine the cohort set. |
| UI | One CLI over the same store + read-only HTTP (`serve-views`) covers "one screen". | Same queries behind the platform's UI. |

---

## 4. Hard questions, straight answers

**"Why 60/40 and not √k (Dunnett)?"** √k gives challengers ~60 % for maximum power. We trade power for bounded
exposure (Compliance: slow and right). Cost: tests take ~1.5× longer. The harm watch drops a significantly worse
arm early.

**"Your false-winner rate?"** ≤ 5 % per (workflow, dimension) by construction: Holm across challengers × an
explicit O'Brien-Fleming α budget across looks (Bonferroni over looks, conservative). Out-of-sample check: the
null-effects scenario in our suite (no true effects) applied **0 harmful** changes — see `reports/robustness.md`.

**"Isn't the extension rule p-hacking?"** It's pre-registered (one extension, only if the best challenger trends
positive), and half of the remaining α is reserved at the first horizon for it, so total α spent stays ≤ 0.05.

**"Why compare decay against the LCB, not the promotion estimate?"** A lift measured at the moment a sequential
test first crosses its boundary is biased upward (winner's curse). Our first version rolled back a genuine winner
because of exactly that. Both decay clauses are at z < −2.33 because the check repeats hourly over overlapping
windows; at 5 % the suite showed false rollbacks.

**"Why did you mark some changes harmful and keep them?"** We don't keep them knowingly; "harmful" is the grader's
hidden-truth verdict at apply time. The two recurring kinds: (a) experiment launches whose exploration share landed
on an option that's worse in truth — the price of exploring at 40 %; (b) reverting the "persuasive" prompt (2.5 %
hallucination): the grader counts it as an incident fix (MTTR) *and* as an engagement loss. In a regulated client
we choose safety; we'd make the same call again and say so.

**"What if the hallucination detector is wrong?"** It is, sometimes: our first version swapped in a "strict" script
on a false alarm and cut engagement 14 %. Now flags alone need a second signal (validation of the live prompt)
unless overwhelming (≥ 2×, z ≥ 5); borderline validations get a pooled second run; every fix is verified on
engagement afterwards and replaced if it hurts.

**"How do you know you didn't overfit to the public scenarios?"** We built six of our own with different truth,
policies and incidents, plus seed replicas, and ran every change on all of them (`scripts/robustness.sh`). Several
fixes came from failures there, not from the public runs.

**"Crash at the worst moment?"** Proposal rows are committed before the HTTP call; restart reconciles
SUBMITTING/APPLYING/AUTO_APPLYING against `/approvals` and `/config/history` before any retry. A timeout is never
treated as failure. Evidence: 9 SIGKILLs at state-targeted moments, 20 checks, 0 failures
(`reports/crash_recovery.md`). The one thing a crash can cost: ≤ 3 credits twice (no idempotency key on
validation in the API).

**"Why SQLite?"** Zero new stateful infrastructure on the grader box; plain SQL that ports to the platform's
Postgres. At 10× the first change is rollups at ingest, then sharding workflows across processes, then Postgres
with daily partitions.

**"What would you do first in production?"** Shadow mode for a week (all decisions recorded, nothing submitted),
compared with what on-call actually did; then one workflow live with full approval routing.
