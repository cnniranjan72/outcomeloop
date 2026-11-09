# Draft: SUBMISSION.md sections 1 and 3

> Paste Part A into `## 1. Assumptions` and Part B into `## 3. Stakeholders`. Policy values quoted below are
> from the `governance` / `objective` / `options` / `mid_flight` blocks that `GET /workflows/{id}` returns for
> public_01 and public_02 (identical in both). `[RESULT: …]` / `[MEASURED: …]` mark numbers that come from runs.

---

## 1. Assumptions

1. **Guardrail `*_max_drop: 0.02`** is an *absolute* drop in the guardrail rate versus the concurrent incumbent
   arm (pickup 0.30 → 0.28 breaches). We also apply a relative reading (drop > margin × 10 = 20 %) and enforce
   whichever is stricter. At public rates the absolute reading binds: 2 pp is 6–7 % of pickup (0.28–0.34) and
   3–4 % of engagement (0.50–0.60).
2. **All governance parameters are read at runtime from `GET /workflows/{id}`**: `approver_hours`,
   `approver_latency_minutes`, `proposal_ttl_hours`, `apply_window_hours`, `max_requests_per_24h`,
   `auto_apply`, `min_validation_pass_rate`. Nothing is hard-coded. Hours quoted in memos are cross-checked
   against the API, never used in place of it.
3. **Approver hours are `[start, end)` IST.** We time submissions against the *worst-case* latency
   (`next_working(now + latency_max)` must fall before `expires_at`), never the mean.
4. **Welcome message and voice are heard only after connect**, so they can only move engagement. We still
   measure pickup per arm as a guardrail. Randomisation is per dial, so a pickup gap between arms would show a
   bug or leakage, not a real effect.
5. **`welcome_message`, `voice` and `caller_id` are sampled independently per dial** (SIMULATOR §3). That is
   what makes a factorial, marginal analysis valid. We check welcome × voice interaction before promoting a
   combination rather than assuming there is none.
6. **An approval cannot be withdrawn.** There is no cancel endpoint. Two open proposals on one workflow would
   race (the second goes `stale_base_version` on apply), so we keep **one open proposal per workflow** and
   batch new changes into the next changeset.
7. **A request over `max_requests_per_24h` is rejected, not refused**, and we assume it still uses up a slot.
   We count expired and rejected requests against the trailing-24h budget and never knowingly submit over it.
8. **`hallucination_flag` is a noisy detector** with false positives and false negatives. We act on flag
   *rates* (≥ 250 connected calls, > 1.5× baseline, z > 3.5), never on single flags. The flag rate is not
   the true hallucination rate.
9. **Validation `pass_rate` measures safety only.** It is noisy (SE ≈ 1 pp at 0.97 with n = 300) and says
   nothing about engagement. A prompt that passes validation still gets engagement verified after it is
   applied.
10. **`history_days` data reflects the business default config only.** It gives baselines, hour-of-day
    profiles and per-DID pickup. It gives no evidence on non-default variants, so dry runs for untried
    variants carry the test design (arms, planned n, achievable MDE) instead of an extrapolated lift.
11. **Returning people keep their `person_id`** across campaigns, and their features don't change; `lead_id`
    is per campaign. Per-person counts are keyed on `person_id`, and campaign membership on `lead_id`.
12. **Credits are one pool per scenario** (`GET /sim/state` → `credits_remaining`, 200 in public scenarios),
    shared by all workflows and tenants. 40 % is held as an incident reserve that routine work cannot spend.
13. **Tenant preferences we adopt voluntarily are stricter than policy.** For Kestrel (`ks_cancel`): ≤ 2
    requests/24h (policy 4) and nothing submitted before 11:00 (policy `approver_hours [10, 19]`). One slot
    per workflow is held for incidents, which leaves Kestrel and `nw_kyc` (policy 2) one routine request a day.
14. **Supervisor edits are legitimate and authoritative.** A `config_changed` event with `actor: supervisor`
    becomes the new base. For 48 h, routine changesets drop any patch to a dimension the supervisor touched. We
    only revert a supervisor edit for safety, through an approval that says so and carries validation evidence.
15. **Customer-facing dims** are `welcome_message`, `voice`, `prompt_version`, plus `cohorts` (which change who
    hears what). **Operational dims** are `caller_id` and `schedule`. No public policy permits auto-applying
    `cohorts` or `prompt_version`, so creating a cohort always needs one approval.
16. **`max_shift` is the total-variation distance per cohort per agent dimension per change** (welcome, voice,
    caller_id). The contract puts no shift cap on `schedule`. We bound hour weights to [0.25, 4] and never use
    0, because 0 can strand capacity.
17. **`mid_flight: next_campaign_only`** (`nw_kyc`) fixes cohorts and allocations per campaign when the campaign
    is created. With cadence `[2, 2, 3]`, an allocation change reaches all `nw_kyc` traffic only after three
    campaign days. Analysis uses each call's own `config_version`, not the current config.
18. **The business owns cadence, dialling windows and capacity.** `schedule.hour_weights` only changes *who* is
    dialled in an hour, never how many are dialled.
19. **"Named human approval"** (Northwind) maps to the simulator's `approval_id` + `decided_at`. The API gives no
    approver identity. In production we would record the approver's name from the client's approval system.
20. **Time zone is IST (+05:30) throughout.** That covers dialling windows, approver hours and Kestrel's 11:00.
    D0 = `2027-01-04T00:00+05:30`.
21. **Grader box is 4 vCPU / 8 GB Linux.** One single-threaded process, Python stdlib plus the pinned
    requirements. The simulator only moves on `POST /sim/advance`, so concurrency would buy nothing.
22. **SQLite (WAL, `synchronous=FULL`) is acceptable as the embedded store for the assignment.** It is a file,
    not a service. In production the same plain-SQL repository layer targets the platform's existing
    Postgres.

---

## 3. Stakeholders

### 01 — Nikhil Rao, VP Sales

- **Accepted.**
  - Show a lift figure per workflow: the primary KPI versus baseline with its confidence interval, and the
    guardrail beside it. Source: `sim grade` reports and our audit store. `[RESULT: public_01/02 lift per workflow]`
  - Fewer, bigger requests: one open proposal per workflow carries the whole batched changeset (proposal state
    machine, §6).
  - Speed where the policy allows it: caller-ID rotation and schedule changes auto-apply on `nw_renewal`
    (`max_shift 0.5`) and `ks_cancel` (`max_shift 0.2`) without waiting for an approver.
- **Pushed back / declined.**
  - **No blended score**, for a client or in a deck. The README and Product both forbid it.
  - **"Winning by lunch, live by evening" is declined.** Sample size, approver latency and `mid_flight`
    rules make it impossible (below). Promoting early is how false winners ship.
  - **Approvals stay.** We cut how *often* we ask, not *whether* we ask.
  - **No "persuasive" prompt rollout** without per-workflow validation and an engagement test.
- **Claims that are wrong against the actual policy/contract.**
  - *"Kestrel turned on auto-apply for everything."* False. `ks_cancel` has
    `auto_apply.allowed_dims = [schedule, caller_id, welcome_message, voice]` and `max_shift 0.2`.
    `prompt_version` and `cohorts` are not auto-appliable. Even for allowed dims, moving a winner from 0 % to
    85 % takes at least 5 separate auto-applies (0.2 TV each). Kestrel's supervisor has also asked to be told
    before customer-facing changes, so we send welcome and voice through approval anyway.
  - *"Northwind is fine with auto-apply on KYC."* False. `nw_kyc` has `auto_apply.enabled = false`,
    `allowed_dims = []`, `max_shift 0`, so every change needs approval, including timing and caller ID.
    Northwind's Head of Compliance requires a named human approval for anything customer-facing. A QBR remark
    doesn't change the signed policy.
  - *"Roll out the persuasive prompt wherever it's available."* The catalog describes P4 as "Persuasive: freer
    objection handling and richer benefit explanations". P4 is only an option on `nw_renewal` and
    `ks_cancel`; `nw_kyc` offers only `[P1, P3]`.
    - Prompt changes are never auto-appliable anywhere. Approval requires a validation run for *that workflow
      and prompt* with `pass_rate ≥ min_validation_pass_rate` (0.97).
    - Another account's demo is not evidence. Product's rules are that evidence comes only from what ran, and
      that winners stay in their own workflow.
    - "Freer … richer benefit explanations" is the profile most likely to hallucinate benefit claims in BFSI.
  - *"Single blended score / one figure per client."* This contradicts README §1 and Product. Even "one figure
    per client" would blend KPIs, because Northwind's two workflows have different primaries: `nw_renewal`
    optimises engagement, `nw_kyc` optimises pickup.
  - *"Winning by lunch, live by evening."* Three things rule it out.
    - **Sample size.** At MDE 8 % relative, α 0.05 family-wise, power 0.8, an engagement test at ~0.55 needs
      ~1,600–2,000 connected calls per arm. `nw_renewal` produces ~1,080 connected calls a day in total
      (300 dials/h × 12 h × ~0.30 pickup). One challenger at a 40 % share needs about 4–5 days.
    - **Approver latency.** `nw_kyc` approvers take 60–480 min within 10:00–18:00, so a noon request can be
      decided the next day.
    - **`nw_kyc` is `mid_flight: next_campaign_only`.** An approved allocation reaches only campaigns created
      from the next 08:00 batch, and all traffic only after 3 campaign days.
- **The reply you'd send them.**

  > Nikhil, I can give you an honest per-workflow lift number for the summit, with the guardrail next to it. I
  > can't give you a blended score: pickup and engagement are separate KPIs by product rule. Two facts to
  > correct. Kestrel's policy allows auto-apply only for timing, caller ID, welcome and voice, in steps of 20 %;
  > prompts always need approval. Northwind KYC has auto-apply disabled entirely. "Winning by lunch" is noise:
  > a real winner needs 4–5 days of calls on these volumes. The persuasive prompt isn't offered on KYC and must
  > pass validation per workflow before anyone sees it. The story I can stand behind: "it improved itself, and
  > the client signed off on every change."

### 02 — Meera Iyer, Head of Compliance, Northwind Life

- **Accepted.**
  1. *No customer-facing change without approval.* Welcome, voice, prompt and cohort changes on `nw_renewal`
     and `nw_kyc` go only through `/approvals` (proposal state machine). We never use auto-apply for them.
     On `nw_renewal` we auto-apply only `caller_id` and `schedule`, as the policy allows, and list each one with
     its reason in the supervisor view (`python -m outcomeloop supervisor`) and the weekly summary.
  2. *Script changes need validation evidence.* Every prompt proposal carries `evidence.validation_run_id` for
     that workflow and prompt, with `pass_rate ≥ 0.97`, and the approver enforces it too. After applying, we
     check the hallucination flag rate and engagement.
  3. *"Why did this customer hear this?"* Every call row stores the `variant` it was dialled with,
     `config_version` and `cohort_id`. `python -m outcomeloop why <wf> --at <time>` joins the config version to
     its proposal, approval, evidence and what happened next. That answers in minutes, well inside 24 h.
  4. *Slow and right.*
     - Challenger traffic is capped at 40 %.
     - A challenger significantly worse than the incumbent (z < −1.645, ≥ 200 connected) is dropped.
     - The **cohort harm check** keeps the incumbent in any cohort where the winner is worse.
     - Every promotion keeps a 15 % holdout so decay is detected.
  5. *Approver hours.* The policy matches her memo: `nw_renewal [10, 19]`, `nw_kyc [10, 18]`. We submit only
     when the worst-case decision time falls inside approver hours and before expiry. Nothing is sent at night.
- **Pushed back / declined.**
  - *"Even briefly."* An experiment exposes some customers to a challenger by definition. We can bound the
    exposure and stop early on harm, but we can't promise zero exposure.
  - *Named approval.* Our approval channel records an approval ID and timestamp, not a person. We need
    Northwind's approver identity passed through to log a name.
  - *Caller-ID rotation on renewal.* We will rotate a degraded number without asking first, as the policy
    allows. A flagged number hurts pickup for every customer, so waiting is the riskier choice.
- **Claims that are wrong against the actual policy/contract.**
  - *"Call timing and caller-ID rotation are covered by the policy we signed."* True for `nw_renewal`:
    `auto_apply.enabled = true`, `allowed_dims = [schedule, caller_id]`, `max_shift 0.5`. **False for
    `nw_kyc`:** `auto_apply.enabled = false`, `allowed_dims = []`. On KYC even a caller-ID rotation or a timing
    change needs an approval. With `max_requests_per_24h 2` and latency 60–480 min, fixing a degraded KYC
    number can take most of a working day.
  - Even on renewal, `cohorts` is not auto-appliable. Timing *per cohort* needs one approval to create the
    cohorts; after that, adjusting hour weights is covered by the policy.
- **The reply you'd send them.**

  > Meera, we accept all five conditions. Opening line, voice and script changes go through your approvers
  > only, never auto-apply. Script changes carry a validation run of at least 97 %. Every call records the
  > variant and config version it ran under, linked to the approval and the reason, so an auditor's question
  > takes minutes. One correction: your policy lets us adjust timing and caller ID automatically on Renewal,
  > not on KYC. KYC has auto-apply disabled, so we'll ask there too. We don't send requests outside 10:00–19:00
  > (KYC 18:00). Exposure in a test is capped and stopped early on harm, not zero. Please let approvals record
  > the approver's name.

### 03 — Kabir Menon, Platform & SRE

- **Accepted.**
  - *Kill/restart test.* There is a scripted kill at random points mid-run, a restart, and a check that the run
    finishes correctly with no double-apply. `[RESULT: see reports/crash_recovery.md]`
  - *Idempotency.*
    - Each chunk's rows and its checkpoint commit in one transaction, with `INSERT OR IGNORE` on the event key.
    - Proposal rows, with their deterministic `proposal_id` and full body, are committed *before* the HTTP
      call.
    - On restart we reconcile against `GET /approvals` and `/config/history` before any retry. A timeout is
      never treated as a failure.
  - *Actionable alerts.*
    - **Page on:** ingest stalled, credits approaching the incident reserve, an approved change about to lapse
      (apply window 2 h), a crash loop. Each message names the workflow and the decision row.
    - **Don't page on:** KPI drift and caller-ID degradation; these go to the supervisor view.
  - *Loop health without logs.* The `metrics` table records ingest lag, events/s, decisions per hour, credit
    burn and backlog, readable from the CLI. `[CMD: health view name]`
  - *< 10 min per simulated day on `public_03_load`.* `[MEASURED: see reports/public_03.md]`
  - *Breaks at 10×.* `[MEASURED: see reports/public_03.md]`
- **Pushed back / declined.**
  - *Redis is not used.* There is no queue or cache to share in a single-process loop.
  - *"The clock doesn't wait" is only partly met.* The loop is synchronous because the simulator pauses for
    it. In production, ingestion has to be decoupled from decision-making. We describe how, but haven't built
    it.
- **Claims that are wrong against the actual policy/contract.**
  - None. One note: the 21:30 deploy falls outside every dialling window (`[9, 21]`, `[10, 20]`), so the kill
    test that matters is mid-day, mid-approval. That is the case we test.
- **The reply you'd send them.**

  > Kabir, no new stateful infrastructure: state is one SQLite file embedded in the process (WAL, fsync on
  > commit). It maps onto your existing Postgres for production, and Redis isn't needed. The kill/restart
  > evidence is in the repo: nine hard kills at chosen moments (mid-ingest, with an approval pending, approved but
  > not applied, with a paid validation in flight, with a governance write in flight), each followed by a resume,
  > no double-apply and no lost approval. Idempotency comes from transactional checkpoints and proposal IDs persisted before any call.
  > Pages fire only for stalled ingest, credits near the incident reserve, an approval about to lapse, or a
  > crash loop. KPI drift waits for morning. On load: [SCALE_REPLY]. At 10× the first thing to go is ingest on
  > one core; the fix is sharding workflows across processes, which I prototyped and measured.

### 04 — Anita Desai, Operations Supervisor, Kestrel Finance

- **Accepted.**
  - *Two requests a day, not before 11:00.* Adopted, although policy allows 4/24h with `approver_hours
    [10, 19]`. One slot is held for incidents.
  - *Five things in one request.* Changes are batched into one changeset per workflow.
  - *One screen.* `python -m outcomeloop supervisor` shows what's being tested, what's winning, what we need
    from her, and what changed today and why. It uses the same cohort IDs as the experiments.
  - *Tell me before anything changes on a running campaign.* `ks_cancel` is `mid_flight: allowed`, so every
    change hits running campaigns from the next tick. Policy would let us auto-apply welcome and voice
    (`max_shift 0.2`). We don't: every customer-facing change goes through her approval.
  - *Compliance-script story.* A low-hallucination prompt can still kill engagement, because validation
    measures safety only. After any prompt change we verify engagement against the guardrail and reopen if it
    drops.
- **Pushed back / declined.**
  - *"Don't undo my changes."* We never revert silently. But a supervisor's prompt edit bypasses validation,
    and public_02 includes a supervisor prompt edit on `ks_cancel` (catalog: "adds payment-urgency language and
    benefit claims") that leads to a hallucination incident. Then we send her an approval request to revert,
    with validation evidence and the flag-rate data. She decides.
  - *Operational changes aren't pre-announced.* Caller-ID rotation and schedule auto-apply within policy and
    appear in "changed today" with the reason. A spam-flagged number shouldn't wait for an 11:00 slot.
  - *Cost of her limits.* Two requests a day, one held for incidents, leaves one routine request a day, so
    experiments on her line run slower.
- **Claims that are wrong against the actual policy/contract.**
  - None are false, but her expectations are stricter than the policy. The signed policy permits 4
    requests/24h from 10:00. It also permits auto-applying welcome and voice changes on running campaigns
    without telling her first. We follow her rules voluntarily.
  - Her prompt edits aren't held to the validation bar (≥ 0.97) that our prompt changes must clear.
- **The reply you'd send them.**

  > Anita, agreed: at most two requests a day, none before 11:00, everything batched. Your screen shows
  > what's being tested, what's winning, what we need from you, and what changed today. We won't touch your
  > prompt edits behind your back. If one triggers a spike in hallucination flags, you'll get a revert request
  > with the validation evidence, and you decide. Anything a customer hears goes through you first. Caller-ID
  > and timing changes apply within your policy and appear on the screen with the reason. After any script
  > change we check that callers still stay on the call, not just that nobody hallucinated.

### 05 — Tara Kulkarni, Head of Product

- **Accepted.**
  - *Separate KPIs.* Every experiment has a primary metric and a guardrail. Neither is blended, in reports or
    in the supervisor view.
  - *One cohort object.* The `cohorts` table is mirrored 1:1 into `config.cohorts`. We assert on ingest that
    the simulator's `cohort_id` agrees. Feature slices are candidates only and are never shown as cohorts.
  - *Minimum cohort size and window.*
    - Choices: **10 % share of dials**, **max 6 cohorts**, **MDE 8 % relative**, **α 0.05 family-wise** (Holm
      across challengers), **power 0.8**, **max 5 days**, then "no evidence, no change".
    - Sizes this gives: ~1,600–2,000 connected per arm at engagement ~0.55, or ~1,300–1,600 at 0.60.
    - Cost in speed: a real 4 % effect is detected only ~30 % of the time, and the 5-day cap retires some real
      winners unproven.
    - Cost in false winners: per dimension-experiment, at most a 5 % chance of promoting a non-winner.
    - Halving the MDE would roughly quadruple test length.
  - *Impact score.* A conservative (lower-bound) expected relative lift on the primary KPI × share of the
    workflow's dials affected, clipped to [0, 1]. The queue order is therefore expected concluded leads, not
    novelty.
  - *Diff, affected leads, dry run.* Every approval request carries them. The dry run states its limits (for
    example, schedule replay ignores pool depletion).
  - *Expired = rejected.* We re-plan from fresh data with a new `proposal_id` and never resubmit the old body.
  - *Evidence only from what ran.* Stats come from each call's actual `variant`, under config versions that
    belong to the experiment. An arm that never ran has n = 0.
  - *Winners stay local.* Winners update only their own workflow.
  - *Wishlist.* Built: caller-ID health (C5) and the consolidated supervisor view (C11).
- **Pushed back / declined.**
  - **Per-person call time is not rolled out blindly**; cohort-level call time (`hour_weights` per cohort) is the
    default, and per-person preferred hours run as a randomised, self-terminating experiment (`persontime.py`).
    - Per-person evidence is a handful of dials at ~30 % pickup, so a person's "best hour" is mostly noise.
    - `lead_preferred_hour` multiplies weight by 6 in the chosen hour but by **0.25 in every other hour**, so a
      wrong guess actively pushes the person out of hours that worked.
    - So treated and control people are compared on pickup per dial; the feature stays only on evidence and only
      where `schedule` is auto-appliable (ablation over 16 runs: +0.93 pp, `reports/ablation_person_time.md`).
  - *Rank the queue by impact score.* Accepted, but with one open proposal per workflow, ranking applies
    across workflows, not within one.
- **Claims that are wrong against the actual policy/contract.**
  - None against the contract. Two nuances:
    - The simulator does distinguish `expired` from `rejected`. We treat both as rejection for planning but
      record which it was, and an expired request still counted against the 24 h request budget.
    - The API requires diff, affected leads and dry run only on approvals, not on auto-apply. We compute and
      store them for auto-applies too, so the surface is consistent.
- **The reply you'd send them.**

  > Tara, all seven definitions are in. On the open questions: cohorts need at least 10 % of dials,
  > with at most six per workflow. Tests are sized for an 8 % relative lift at 5 % family-wise error and 80 %
  > power, capped at 5 days. The cost: effects under ~5 % mostly go undetected, and some real winners expire
  > unproven. In exchange, false winners stay rare. The impact score is a conservative expected lift × share
  > affected, so ranking by it is meaningful. Caller-ID health and the supervisor view are built. Per-person
  > call time runs as a randomised experiment, not a rollout: a handful of dials per person rarely picks a best
  > hour, and the 0.25× penalty punishes wrong guesses, so it stays only where treated people out-pick controls.
  > Cohort-level timing is the default.

### 06 — Aryamann, CTO

- **Accepted.**
  - *Explainable beats bigger.* Every decision, no-ops included, is a row in the append-only `decisions`
    table. `python -m outcomeloop why <wf> --at <time>` answers "who, why, what next". Customer-facing changes
    always go through approval.
  - *Hurting a cohort is worth less than nothing.* The cohort harm check runs before promotion, harm stopping
    applies during tests, and holdout-based decay detection (15 % holdout) catches winners that stop winning.
  - *No compute that doesn't change a decision.*
    - Incident fixes try our own last known-good prompt before calling `suggest-fixes`.
    - Validation runs at n = 300 (3 credits).
    - An LLM never chooses a winner.
    - 40 % of credits is an incident reserve. `[RESULT: credits used on public_01/02]`
  - *Scale.* Transactional, idempotent chunk ingestion; [SCALE_REPLY] (`reports/scaling.md`). We state what
    breaks first at 10× and how we'd partition by tenant and workflow.
  - *Choosing.* Per-person call time ships as an experiment rather than a rollout; the cuts in §2 each have a
    drafted message.
  - *Own it next month.* There is a runbook for each page and a restart procedure. `[RESULT: docs link]`
  - *Trust the contract.* Each memo claim was checked against `GET /workflows` policy; the false ones are
    listed above.
- **Pushed back / declined.**
  - *"Hundreds of workflows without an engineer"* is limited by approvers, not compute: 2–4 requests per
    workflow per day, minus our own reserve. Autonomy at scale comes from batching and auto-apply where policy
    allows.
  - The cohort harm check covers the cohorts we define, not every possible feature slice. A harm that is
    confined to an undefined slice can still slip through.
- **Claims that are wrong against the actual policy/contract.**
  - None in this memo. As he predicted, wrong claims appear in Sales (Kestrel and KYC auto-apply, P4),
    Compliance (KYC timing and caller ID) and, by omission, Kestrel (expectations beyond the policy).
- **The reply you'd send them.**

  > Aryamann, I chose depth over breadth: governance, experiments with cohort harm checks and decay rollback,
  > caller-ID health, hallucination response, and a full audit trail. Per-person call time runs as an experiment, and the cuts
  > are listed with reasons and drafted messages to the people affected. Every change on a client agent can be
  > explained from our own store in one command. Credits go first to known-good fixes, and 40 % is reserved for
  > incidents. On scale: [SCALE_REPLY]. The first bottleneck at 10× isn't compute but
  > approver capacity at 2–4 requests per workflow per day. I've designed around that with batching. Three
  > memos contained claims the policies contradict; I followed the policies.
