# OutcomeLoop architecture

This document is for engineers who will change the code. It describes what the code in `src/outcomeloop/`
does today. `docs/DESIGN_DECISIONS.md` is the spec the code was built against. Where the two differ, this file
follows the code, and the differences are listed in the last section. The diagrams referred to below (A–G) are
in `README.md`.

## 1. Process model

There is one process (`python -m outcomeloop run`), one thread and one SQLite connection. The tick is 15
simulated minutes (`Settings.tick_minutes`). Decisions run on the hour (`decision_every_minutes = 60`), or at
the next tick for workflows marked urgent. Today only a supervisor prompt edit marks a workflow urgent.

```
startup():  _prepare_db (world check) -> meta -> workflows -> ingest_all (history backlog)
            -> controller_start|controller_restart decision -> reconcile_all -> handle_inbox -> _sync_config
loop:       governance_tick -> decide(wf) for due workflows -> advance(15) -> ingest_all -> handle_inbox -> _metrics
finish():   controller_finish decision
```

There are three error domains:

- **Inside `decide(wf)` and `governance_tick`.** The exception is caught, the open transaction is rolled back, an
  `error` decision is written, and the loop continues.
- **Inside one inbox handler.** The transaction is rolled back, an `error` decision is written, and the event is
  marked done. This is a poison-message guard.
- **Anywhere else (ingest, advance, startup).** The exception ends the process. `run.sh` restarts it from
  durable state after 5 s, up to `OUTCOMELOOP_MAX_RESTARTS` times.

## 2. Modules

### `simclient.py`: the only door to the world

- **`_get`** retries transport errors and 5xx with exponential back-off (0.5 s doubling to 10 s, 5 retries).
- **`_write`**:
  - retries only `httpx.ConnectError`, which means nothing was sent;
  - raises `Uncertain` on any other transport error or 5xx;
  - raises `ApiError(status, code, detail)` on 4xx, with `code` read from the body's `error` field.
- **`advance`** may be retried on connect errors. Callers handle `Uncertain` by re-reading `/sim/state`.
- **`suggest_fixes` and `validate`** use `retry_connect=False`, so they are never retried.
- **`iter_chunk`** downloads a whole NDJSON chunk before yielding any event. A failed download is retried as a
  whole, and a partly read chunk never reaches the DB.

### `db.py`: storage primitives

- **Connection setup:** `isolation_level=None`, so transactions are explicit. WAL, `synchronous=FULL`,
  `temp_store=MEMORY`, about 200 MB page cache.
- **`tx()`** is nesting-safe: an inner `with db.tx()` joins the outer transaction, and only the outermost
  commits. `begin()` uses `BEGIN IMMEDIATE`.
- **`code(kind, value)`** maps strings (workflow ids, cohort ids, options, feature values) to small integers,
  cached in memory. `rollback()` reloads the cache from the table, so a code created inside a rolled-back
  transaction is forgotten.
- **`decide(...)`** appends one audit row. **`metric(...)`** appends one metric sample.

### `ingest.py`: exactly-once ingestion (C1)

- **`pending_chunks`** lists `history` and `events` chunks after `MAX(chunks.chunk)`, merged and sorted by chunk
  number.
- **`ingest_chunk`** works in one transaction:
  1. skip the chunk if it is already in `chunks`;
  2. stream the events;
  3. batch `INSERT OR IGNORE` into `persons`, `leads`, `campaigns`, `calls`, `config_versions` and `inbox`, and
     `UPDATE leads.concluded_minute` for engaged calls;
  4. insert the `chunks` row with timing.

  On any exception the in-memory `FeatureStore` is rebuilt from `persons` before the exception propagates.
- **`FeatureStore`** holds, per workflow, a numpy `int32` array indexed by person number. Each value packs
  `lang<<12 | tier<<8 | age<<4 | val`. Person and lead ids are parsed from their numeric suffix
  (`...:p0004567` becomes 4567).
- **The inbox** receives `config_changed` and `approval_decided` events for side-effect handling.

### `cohorts.py`: shared cohort object (C2, C3, C4)

| Function | What it does |
|---|---|
| `Cohort`, `cohort_id_for` | Deterministic ids such as `age_60p` or `lang_ta`. |
| `membership_sql` | The only implementation of first-match membership: a SQL `CASE` over the integer feature columns. |
| `load_cohorts` / `save_cohorts` | `save` retires the current proposed/live set and upserts the new one with positions. |
| `bootstrap_cohorts` | Picks the feature by likelihood-ratio test and merges groups to at least a 10 % share and at most 6 groups. |
| `schedule_weights` | Empirical-Bayes-smoothed per-cohort hour weights, plus the re-weighting dry run. |

### `detectors.py`: population detectors

| Function | Signal |
|---|---|
| `did_health` | Per caller ID: pickup vs the pooled other numbers, in fast (6 h), slow (24 h) and long (72 h, healthy-only) windows; degraded also needs a > 15 % drop against the number's own previous week when it has one (`did_own_past`, cached 6 sim-hours); a re-probed number's windows start at its probe. Returns `healthy` / `degraded` / `unknown` with per-window evidence. |
| `halluc_baseline` | Per prompt over all calls before `until`: connected, flags, engaged, rates. |
| `halluc_spike` | The live prompt's flag rate since `since` (at most 24 h) vs the reference rate. Fires at n ≥ 250, rate > 1.5 × reference and z > 3.5. |
| `kpi_drift` | Last 24 h vs the 7 days before, for pickup (≥ 1000 dials each) and engagement (≥ 500 connected each). Raises an alert at a relative drop > 5 % with z < −3. |

### `experiments.py`: C6 and C7

- **`Experiment`** is a dataclass serialised to `experiments.data`. Fields:
  - arms, incumbent, design
  - status, start minute and version, the experiment's config versions
  - dropped arms, `p_base`, `n_plan`, `achieved_mde`
  - `t_prev`, `alpha_spent`, `horizon_days`, `extended`
  - looks, winner, plan, promo, `promoted_minute`, result
- **`ExperimentEngine`** provides `arm_counts`, `design`, `on_config`, `look`, `plan_promotion` / `plan_drop` /
  `plan_no_winner`, `decay_check` and `plan_rollback`. The README covers the rules.
- **Arm counts** come from `calls` rows whose `cfg_ver` is in `e.versions`, grouped by `membership_sql` cohort
  and by the variant column the call actually ran with.

### `governance.py`: C9

`Governance` provides:

- **queries:** `open_proposal`, `requests_last_24h`
- **rules:** `fatigue_cap`, `can_request`, `submit_window`
- **writes:** `submit`, `auto_apply`
- **progress:** `tick`, which polls and applies, and `_apply`
- **recovery:** `reconcile_all`, `reconcile_submitting`, `reconcile_applying`, `reconcile_auto`

Every remote write is preceded by a committed intent row.

### `controller.py`: the loop and the planner

- The loop, startup and the world check.
- Inbox handlers (`_on_config_changed`, approval audit).
- `decide()` and its steps (section 4).
- The config algebra (section 5).
- Proposal assembly: `_submit`, `affected_leads`, `impact`, `_proposal_rationale`.
- Auto-apply ramping: `_auto_step`.
- Metrics.

### `views.py`: read side (C11, C12, C14)

`why`, `supervisor`, `status`, `audit` and `customer`. These commands only read SQLite. `why` takes the config
version in force at T (the latest version at or before T + 15 minutes), then prints:

- the proposal behind it, with approval id and timestamps, summary, impact, affected leads, rationale and diff;
- the decisions of the relevant kinds in the 3 days before;
- everything in the 48 h after;
- KPIs for the 24 h before and after.

For a supervisor version, it prints our reactions in the following 6 h.

### `stats.py`, `timeutil.py`, `config.py`

These hold the deterministic statistics, the sim-time arithmetic and the constants. Every threshold named in
this document is a field of `Settings`.

## 3. Data model

All tables are created by `db.SCHEMA`, except `inbox`, which `ingest.INBOX_SQL` creates. Times are **sim
minutes** (`D0 00:00` = 0; history is negative), unless a column is called `wall` or `ingested_at`, which are
Unix seconds. `wf` is the integer code of a workflow id. Option and feature columns hold codes from `codes`.

| Table | Column meanings |
|---|---|
| `meta(k, v)` | World fingerprint: `scenario` (from `/sim/state`) and `first_history_event` (`last_event_id` of the first history chunk). |
| `kv(k, v)` | JSON controller memory per workflow: `boot`, `schedule` (hour weights + dry run), `halluc_ref` (rate + by prompt), `did` (per-number state, since, rest), `locks` (dim → minute until), `blacklist` (option → minute until), `prompt_probe`, `halluc_quiet`, `ramp:<wf>:<day>` (TV moved today), `hold` (last hold reason, so repeats aren't re-logged), and `credits_start`. |
| `codes(kind, value, code)` | String ↔ int dictionary. `kind` is `wf`, `cohort`, `welcome_message`, `voice`, `caller_id`, `prompt_version`, `lang`, `city_tier`, `age_band` or `value_band`. |
| `chunks` | Ingest checkpoint: one row per ingested chunk. `kind` (history/events), event count, first and last event id, `until_minute`, wall time and seconds spent. |
| `workflows` | `wf` code, `workflow_id`, `tenant_id`, and `spec`, the full `GET /workflows` JSON: options, cadence, window, objective, governance policy. |
| `persons` | Per workflow and person: feature codes. |
| `leads` | Per workflow and lead: person, campaign day, and `concluded_minute` (the first engaged call, otherwise NULL). |
| `campaigns` | Campaign id, day, size, config version at creation. |
| `calls` | One row per call event, `PRIMARY KEY (wf, minute, event_id)`, `WITHOUT ROWID`. `cfg_ver` and `cohort` are as reported by the simulator. `wm`, `voice`, `did`, `prompt` hold the variant actually dialled. `conn`, `eng`, `flag` are 0/1. `lang`, `tier`, `age`, `val` are joined at ingest. |
| `config_versions` | Every version observed. `actor`, `minute`, `changed_dims` (JSON), `proposal_id`, `approval_id` and `event_id` come from the `config_changed` event. `config` is the full config, filled from `GET /config` when the event is handled. |
| `cohorts` | `cohort_id`, `position` (match order), `where_json`, `status` (`proposed` → `live` when the live config carries the set → `retired`), `rationale` (bootstrap evidence JSON). |
| `experiments` | `experiment_id` = `exp-<wf>-<dim>-<minute>`, `status`, `data` (the full `Experiment` JSON). |
| `proposals` | `route` (`approval` / `auto`), `state`, `kind` (`routine`, `urgent`, `incident`, `operational`), `base_version`, `body` (the exact request), `approval_id`, `approval` (the last remote object), `applied_version`, `notes` (error detail). |
| `incidents` | `incident_id` = `inc-<workflow>-<minute>`, `type` = `hallucination`, `state` (`open`, `fix_ready`, `proposed`, `verifying`, `closed`), `data` (bad prompt, trigger evidence, `tried`, LLM suggestions, fix, verification). |
| `credits_ledger` | One row per credit-spending call. `kind` (`validation` / `llm`), `purpose`, `state` (`sent` → `done` / `failed`), `cost`, `request`, `response`. |
| `decisions` | Append-only audit. `kind` (for example `bootstrap`, `did_health`, `experiment_*`, `proposal_*`, `auto_apply`, `hold`, `incident_*`, `validation_run`, `config_changed`, `supervisor_edit`, `alert`, `error`, `recovery_reconcile`), `actor` (`controller`, `approver`, or the config actor), `summary`, `reasoning`, `evidence` (JSON), `outcome`, and link columns. |
| `metrics` | `name`, `value`, `labels` (JSON). See README › Observability. |
| `inbox` | `event_id`, `type`, `wf`, `minute`, `payload` (raw event), `done`. |

## 4. The decision tick, step by step

`Controller.decide(wf)` (hourly, or on the next tick if urgent):

0. **Bootstrap** on the first call for this workflow (`kv boot:<wf>` absent). The window is from the first call
   in the DB up to `min(now, 0)`. This step:
   - runs `bootstrap_cohorts` and saves the result as `proposed` cohorts;
   - runs `schedule_weights` and saves the weights and dry run in `kv schedule:<wf>`;
   - runs `halluc_baseline` and saves the reference rate in `kv halluc_ref:<wf>` (default 0.015 if there is no
     history);
   - writes a `bootstrap` decision with all the evidence.

   Then it reads the live config with `GET /workflows/{id}/config`, and reads the active supervisor locks.
1. **`detect_did`.** Runs `did_health` with probing = numbers in `unknown` / `probe` state, then applies the
   state machine (healthy / degraded / probe, rest doubling, 24 h probe box). It writes a `did_health` decision
   per transition. If any number became degraded, the workflow is marked as an emergency.
2. **`detect_halluc`:**
   - If a supervisor prompt probe is queued and that prompt is still live, it validates the prompt. Below the
     approver's gate opens an incident; passing only on the point estimate (95 % bound above the limit) buys a
     pooled second run when credits allow, and an incident if that still does not show the prompt clears the gate.
   - It computes `halluc_spike` since the last prompt change (at most 24 h). If the detector fired, no incident is
     open, and the prompt is not muted, it opens an incident.
   - It then advances the open incident:
     - `open`: confirm (flag-triggered only), then `_find_fix`. If a fix is ready, it is handed to the planner as
       an emergency.
     - `fix_ready`: hand to the planner, or move to `verifying` if the fix is already live.
     - `proposed`: if the proposal ended `REJECTED` / `EXPIRED` / `LAPSED` / `STALE` / `SUBMIT_FAILED`, go back to
       `fix_ready` and write `incident_repropose`.
     - `verifying` (at least 4 h after apply): run the engagement check, then verify, close unverified after
       24 h, or re-open if harmful.
3. **KPI drift**, only when `now % 1440 == 720` (12:00). Writes an `alert` decision if there is a pickup or
   engagement drop. It never changes config.
4. **`step_experiments`**, for each of `welcome_message` and `voice`:
   - No active experiment: check eligibility and cool-downs, then `design`, then write `experiment_designed`.
     The design is only a plan; it starts when its allocation is live in config.
   - `running`: at the look hour (after at least 20 h) or at the horizon, run `look`, then `_apply_look` (extend,
     promote, no winner, drop, or continue). Between looks, the hourly harm watch drops arms at z < −2.33.
   - `promoted`: run `decay_check`. If anything decayed: `plan_rollback`, blacklist the winner, write
     `decay_detected`, and mark the workflow urgent (emergency) for routing.
5. **`desired_config`.** Starts from a deep copy of the live config and changes only what is not locked:
   - **Cohorts and schedule:** our cohort set (proposed or live) and its hour weights, if the live config has no
     cohorts or already has exactly ours. Existing `lead_preferred_hour` entries are kept.
   - **Caller ID:** the `did_target` allocation, if it moves by at least 0.05 TV or a degraded number still has
     traffic. In that second case it is marked urgent.
   - **Experiments:** for `designed` / `running` experiments, the design on `default`. Otherwise the plan's
     scopes (default and live cohorts only).
   - **Prompt:** the incident fix.

   Each changed component records a summary and evidence for the proposal.
6. **`route`.** `dims = changed_dims(live, desired)`. If nothing changed, return.
   1. **Prompt fix** (`prompt_version` in dims). If no incident proposal is already open, check `submit_window`
      and `can_request(emergency=True)`, then submit a **prompt-only** proposal and return. Otherwise write a
      `hold`. Prompt is then removed from the remaining dims.
   2. **Split the remaining dims.** `auto_ok` = dims the policy allows for auto-apply, minus customer-facing dims
      and minus `cohorts`. Everything else is `approval_dims`.
   3. **Urgent caller ID** (`auto_ok`): call `_auto_step(urgent=True)`. Return if it applied.
   4. **`approval_dims`**: if a proposal is open, return (one open proposal per workflow). Otherwise check the
      window and fatigue (emergency if caller ID is urgent or a decay was found). Then `_submit` a batched
      proposal covering **all** changed dims, or write a `hold` with the reason.
   5. **Operational auto-apply** (`auto_ok`, no open proposal): call `_auto_step(urgent=False)`. The schedule is
      included only if the desired cohorts are already live.

`_submit` builds the request body:

| Field | Content |
|---|---|
| `diff` | Per dim: cohort ids before and after; hour weights after; prompt before and after; per-scope allocation before and after. |
| `affected_leads` | Active leads with campaign day > today − len(cadence) and not concluded. For `next_campaign_only`, changes without schedule or prompt count `daily_batch.size` instead. |
| `impact_score` | See README › Limitations. The detail is stored in `evidence.impact_detail`. |
| `dry_run` | Per changed component: experiment evidence, schedule dry run, validation, or caller-ID health. |
| `rationale` | Built from templates per component. |
| `expires_in_hours` | Policy TTL. |
| `evidence.validation_run_id` | Included for prompt changes. |

The body goes through `canonical_config`, and the `proposal_submitted` decision stores diff, affected leads,
impact and dry run.

## 5. Config algebra and governance-boundary parity

The simulator decides `changed_dims` and the auto-apply `max_shift` check from its own normalisation. If our
view disagrees with its view, an auto-apply we think is within policy gets a 403, or a proposal reports
phantom dims. `controller.py` mirrors the boundary exactly, and `tests/unit/test_config_parity.py` checks it
against the simulator's implementation on random configs.

- **`_dist(cfg, cohort, dim)`.** The effective distribution for a cohort is its own allocation, otherwise
  `default`, as the simulator samples it.
- **`changed_dims(old, new)`.**
  - `cohorts`: the lists differ.
  - each of `welcome_message`, `voice`, `caller_id`: for any allocation key, the TV distance between effective
    distributions is greater than 1e-9.
  - `prompt_version` and `schedule`: inequality.

  The result is ordered as `CHANGE_DIMS`.
- **`max_shift(old, new)`.** The largest TV distance over `default` plus every cohort id in either config, for
  the three agent dims. This is the quantity the policy's `max_shift` bounds.
- **`_fixpoint(d)`.** The boundary re-normalises what we send (`w / sum(w)`) and then compares with exact
  equality. A distribution that is not a fixed point of that normalisation would read as "changed" on every
  later proposal that copies it. `_fixpoint` iterates the normalisation until it is stable, and breaks a rare
  2-cycle by forcing the largest weight.
- **`canonical_config(old, new)`.** For every allocation in `new`: if its effective distribution equals the
  live one (TV ≤ 1e-9), send the live dict byte for byte; otherwise send its fixed point. All proposals and
  auto-applies go through this.
- **Ramping (`_auto_step`).** When `max_shift(live, step) > policy max_shift`:
  - take a step only if at least 60 minutes have passed since our last applied auto-apply;
  - the remaining daily budget is `3 × max_shift − kv ramp:<wf>:<day>`;
  - `frac = min(max_shift, budget) / shift`, and the caller-ID distribution moves `frac × 0.999` of the way.
    The 0.999 keeps rounding under the cap.

  The applied shift is added to the day's budget.

## 6. Extension points

### Adding a detector

1. Write a pure function in `detectors.py` that takes `(db, wf, ..., now, s)`, queries `calls` (use
   `membership_sql` if it needs cohorts), and returns an evidence dict with a boolean verdict. Require a minimum
   n and a z threshold: no single-call triggers. Put the thresholds in `Settings` with a comment explaining
   where the value comes from.
2. Call it from `Controller.decide` at the right point. Before `step_experiments` if it can change what we plan,
   after it if it only alerts. Keep any per-workflow memory in `kv` (`<name>:<wf>`) and write every state
   transition with `db.decide(...)` inside one `db.tx()`.
3. To make it change config, put the change into `desired_config` (respect `ctx["locks"]`), add a component
   summary and evidence to `ctx["components"]`, and decide its routing in `route` (approval, auto-apply only if
   operational, emergency or not).
4. To surface it: add its decision kind to the alert list in `views.status` and, if relevant, to the kinds
   listed by `views.why`.
5. Tests go in `tests/unit/test_detectors.py`, using `tests/helpers.py` to build call rows.

### Adding a lever (a new config dimension or option family)

1. If the simulator adds a dimension, add it to `CHANGE_DIMS` and, for a per-call sampled allocation, to
   `AGENT_DIMS`. Update `changed_dims` / `max_shift` and extend `test_config_parity.py` first.
2. Add a call-row column in `db.SCHEMA` and fill it in `ingest._ingest_chunk`. This needs a schema version bump.
   Old DBs are archived only on a world change, so add a migration or document a clean start.
3. For a variant you want to experiment on, add it to `experiments.EXP_DIMS` and map the column in
   `ExperimentEngine.arm_counts`.
4. Decide whether it is customer-facing (`Settings.customer_facing_dims`). Customer-facing dims never
   auto-apply.
5. Add rationale text in `_proposal_rationale` and an impact rule in `Controller.impact`.

## 7. Where the code differs from `docs/DESIGN_DECISIONS.md`

The code is authoritative. Each item gives the spec section first, then what the code does.

1. **§1.** The loop order is governance tick → decide → advance → ingest → inbox → metrics. Reconcile runs at
   startup and after each uncertain write.
2. **§2, tables.**
   - The spec names `checkpoint`. The code uses `chunks`.
   - `leads` has `concluded_minute` instead of a status.
   - The code adds `kv`, `codes`, `campaigns` and `inbox`.
3. **§3.** The spec says agreement between our cohort membership and the simulator's `cohort_id` is "asserted
   on ingest". It is not: the simulator's `cohort_id` is stored in `calls.cohort`, but nothing compares it.
   Agreement is covered by a unit test of `membership_sql` against first-match semantics.
4. **§4, detection thresholds.**
   - There is no Bonferroni adjustment over looks per day. The z thresholds are fixed values in `Settings`.
   - The hallucination window is "since the last prompt change, at most 24 h", not a rolling 4 h. Inside
     `halluc_spike`, `halluc_window_minutes × 6` is used.
   - Caller-ID healthy means `ratio − se ≥ 0.85` on ≥ 150 dials in the slow or long (72 h) window. `did_healthy_ratio = 0.92` is not
     used.
   - Numbers on probe use a lower degraded bar: z < −2.33 on ≥ 150 dials.
   - Decay needs 120 connected per arm (`decay_min_connected`), not 150, and compares against the 80 % LCB of
     the lift at promotion, not the lift itself.
5. **§5, experiments.**
   - The primary metric is always engagement and the guardrail is always pickup. `objective.primary` is not
     consulted, and the margin is the value of the workflow's single guardrail entry.
   - There is no welcome × voice interaction check.
   - Planning uses alpha/k per challenger.
   - Harm stopping happens at looks (z < −1.645, ≥ 200 connected) and in an hourly watch (z < −2.33). The
     cohort harm check also needs ≥ 100 connected per arm.
   - Additions not in the spec: the stability check, cohort-level winners when there is no pooled winner, and the
     pre-registered single extension.
6. **§6.** The spec has a 5 % probe only. The code also re-probes previously degraded numbers at 2 % for a
   24 h time box, with rest doubling.
7. **§8, incidents.**
   - The LLM is called once no untried known-good candidate remains.
   - Selection is "first candidate in order that passes", not "then higher pass rate".
   - Verification is "detector not firing on ≥ 100 connected and the engagement check ran", with engagement harm
     defined as relative < −5 % and z < −2. It is not "flag rate under 1.5× and engagement above the
     guardrail".
   - Every current credit spend is incident work, so the 40 % reserve does not bind.
8. **§9, governance.**
   - There are no `DRAFT`, `VERIFIED` or `ROLLED_BACK` proposal states.
   - Stale and expired proposals are not rebased patch by patch. The next decision re-plans from the live config,
     and supervisor-locked dims are skipped.
   - A prompt incident fix may be submitted while a routine proposal is open.
   - The rejection cool-down (4 h) is not in the spec.
9. **§11, impact score.**
   - The promotion score is multiplied by `1 − holdout` (0.85), not by the share of affected traffic.
   - Incident fixes are a fixed 0.9.
   - Decay rollback scores 0.6, schedule scores half its dry-run lift, and caller ID scores 0.7 if urgent and
     0.1 otherwise.
   - Variant dry runs are the experiment's last-look evidence, not a separate per-cohort replay.
