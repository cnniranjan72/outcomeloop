# Adversarial testing — what we attacked, what broke, what we changed

This report lists every attack we ran on the controller, how it was run, what it found, and the regression test
that now pins the behaviour. Nothing here modifies the simulator: attacks use the simulator's real HTTP behaviour,
controlled HTTP mocks (`httpx.MockTransport`), the in-memory `FakeSim` test double, real processes killed with
SIGKILL / TerminateProcess, or scenarios we generated with the simulator's own schema.

Sources of attacks, in the order they were run:

1. **Our own audit trail** while running public_01/02 (early defects; `docs/IMPLEMENTATION_LOG.md`).
2. **Crash-recovery harness** — 9 state-targeted hard kills per run (`scripts/crash_recovery.py`).
3. **Robustness suite** — 6 generated hidden-like scenarios × 2 seeds + both public scenarios
   (`scripts/robustness.sh`, `reports/robustness.md`).
4. **Independent adversarial code review** (read-only, prompted to find crash-safety, governance, statistical and
   performance defects; 20 findings).
5. **Fault-injection unit tests** (`tests/unit/test_adversarial.py`, `test_simclient.py`, `test_governance.py`,
   `test_controller.py`) and process-level tests (`tests/integration/test_crash_restart.py`).

Severity: **C** = could break a mandatory requirement or a safety invariant; **H** = reliability/correctness;
**M** = meaningful; **L** = minor.

## 1. Governance and duplicate actions

| # | Attack | Found | Fix | Pinned by |
|---|---|---|---|---|
| 1 | Two controller processes on the same state file | **C** — nothing prevented it; both would plan, submit and apply (our proposal ids derive from local state, so they can differ for the same intent) | `InstanceLock`: exclusive OS lock on `<db>.lock` before the store is opened; second instance refused; released by the OS on SIGKILL | `test_second_controller_process_is_refused_and_lock_survives_sigkill` (real subprocess, killed) |
| 2 | Crash between "approval received" and "application persisted", at each boundary | Held: intent rows before HTTP + reconcile before retry | — (verified) | apply-boundary crash matrix: `test_crash_after_approval_seen_before_any_local_write`, `..._after_applying_intent_committed_before_http`, `..._after_remote_apply_before_local_commit`, `test_lost_response_on_apply_reconciles_without_resending`, `test_repeated_restarts_are_idempotent` |
| 3 | Supervisor edits config between our approval and our apply | Held: base version checked before calling apply; STALE, never forced | — | `test_supervisor_edit_between_approval_and_apply_is_never_overwritten`, `test_stale_at_apply_never_calls_apply` |
| 4 | Promotion withdrawn (effect faded) while its approval is pending; approver then approves | **H** — the approval was still applied (audit said "withdrawn") | Open request carrying the experiment → `WITHDRAWN`, never applied, still counts toward fatigue | `test_withdrawn_proposal_is_never_applied` |
| 5 | Our own routine approval lands before our incident fix on the same base | **H** — the safety fix went stale and the fatigue cap blocked re-proposal for up to 24 h | Emergency approvals apply first; a routine approval waits while an emergency for the workflow is open | `test_routine_approval_waits_while_an_emergency_is_open` |
| 6 | Approval exists remotely with no local row (state lost / rebuilt) | **M** — only logged; it would never be counted toward the approver's budget. Then (second pass) an orphan that had *already been applied* was labelled `WITHDRAWN` although the config history showed it applied | Open (pending/approved) → `WITHDRAWN`, never applied; terminal statuses recorded as the simulator reports them: `APPLIED` with the version the config history attributes to that approval, `REJECTED`, `EXPIRED`, `LAPSED`; a `recovery_reconcile` decision for each; real creation time; counts toward fatigue | `test_orphan_approval_without_local_context_is_never_applied`, `test_orphan_already_applied_is_recorded_applied_with_its_version_never_reapplied`, `test_orphan_rejected_is_recorded_rejected` |
| 7 | Auto-apply refused (403) | **M** — retried hourly forever; the ramp could overshoot `max_shift` by rounding | A 403 sends the dims to the approval route for 24 h; ramp steps keep a margin and are re-checked after canonicalisation | audit fix, `test_auto_apply_ramps_within_max_shift`, `test_ramp_steps_are_at_least_an_hour_apart` |
| 8 | Supervisor-set caller ID after the 48 h lock | **M** — silently re-spread by auto-apply | A dimension a supervisor set is approval-only until one of our approved changes to it lands | audit fix |

## 2. Event processing

| # | Attack | Found | Fix | Pinned by |
|---|---|---|---|---|
| 9 | Same chunk ingested twice, incl. with its checkpoint deleted | Rows held (`INSERT OR IGNORE`); **H** new hourly rollups would have double-counted | Rollups are recomputed per touched workflow-hour from the stored rows — a pure function, replay-safe by construction | `test_ingest_all_and_idempotent_replay`, `test_rollups_equal_raw_aggregation_and_survive_replay` |
| 10 | Exception mid-chunk | **H** — in-memory code/feature caches kept values from the rolled-back transaction | Caches rebuilt on rollback | `test_ingest.py` atomicity tests |
| 11 | Transient simulator error while handling a supervisor `config_changed` event | **H** — event marked done, supervisor lock never written; next plan would overwrite the edit | Events retried, never dropped (dead-letter after 10); the workflow gets no decisions while it has unprocessed events | `test_supervisor_event_survives_a_transient_failure_and_holds_decisions` |
| 12 | Truncated / malformed chunk response | **M** — `ValueError` outside the retry loop → crash-loop. The first fix (parse the whole chunk into a list before yielding) cost **+487 MB** per 250k-event history chunk (measured) and was the whole of the load-test memory rise; it also missed a response cut exactly at a line boundary | Chunks stream again (constant memory); any incomplete read — transport error, malformed line, 5xx, or fewer events than the listing says — raises `ChunkReadError`; the ingestor rolls the chunk's transaction back and re-reads it whole (bounded). Atomicity comes from the transaction, not from buffering | `test_truncated_or_short_chunk_raises_chunk_read_error`, `test_partial_chunk_is_rolled_back_and_reread_whole[mid_line/line_boundary]`, `test_chunk_that_never_reads_completely_fails_loudly_and_keeps_nothing` |
| 13 | Out-of-order events | Not possible by contract (`event_id` strictly increasing, chunks processed in chunk order); inbox handled in `event_id` order and later events of a workflow wait behind a failed one | — | `test_ingest.py`, item 11 |

## 3. HTTP and process faults

| # | Attack | Found | Fix | Pinned by |
|---|---|---|---|---|
| 14 | HTTP 429 | **M** — treated as a final 4xx | Reads retry 429 honouring `Retry-After`; a write refused with 429 was not processed and is retried | `test_429_on_read_*`, `test_429_on_write_*` |
| 15 | Retry storms | **L** — fixed backoff, no jitter | Full-jitter exponential backoff, 10 s cap | `test_backoff_has_jitter_and_a_cap` |
| 16 | 5xx / timeout after a write was sent | Held: `Uncertain`, reconciled, never resent blindly | — | `test_write_timeout_after_send_is_uncertain_and_not_retried`, `test_unexpected_503_on_write_is_uncertain_not_failure` |
| 17 | Simulator down at start-up / connect hangs | **L** — 120 s per connect attempt | 5 s connect timeout (reads keep a long timeout for `/sim/advance`) | `test_get_retries_are_bounded` |
| 18 | SIGKILL at 9 state-targeted moments (history ingestion, pending approval, approved-not-applied, mid-dial, paid validation in flight, supervisor edit, uncertain submit) | **H** ×2 — a paid validation result could be lost between ledger and incident; a supervisor-prompt probe was forgotten if killed mid-call | Results persisted in the ledger transaction; probe cleared only with its result | `reports/crash_recovery.md` (20 checks, 0 failed), `test_kill_twice_restart_finishes_without_duplicates` |
| 19 | SIGTERM (deploy, `docker stop`) | **M** — bash does not forward signals; the controller only died by SIGKILL | `run.sh` forwards; controller stops between steps, records `controller_stop`, exits 143 | `scripts/graceful_stop_test.sh` (Linux container) |
| 20 | Corrupted state file | **M** — crash-loop; then the recovery path itself leaked a connection that blocked the archive on Windows | `PRAGMA quick_check` at start; damaged store archived (never deleted) and rebuilt from the simulator; connection closed in `finally` | `test_corrupted_state_file_is_archived_and_rebuilt` |
| 21 | One workflow throws on every decision | **H** — isolation kept the process alive but hid the failure (one error/hour never tripped the >5/hour page) | New page: ≥ 3 errors for one workflow in 3 sim-hours; robustness summary reports decision errors (0 in all final runs) | `test_persistent_low_rate_error_on_one_workflow_pages`, `test_pending_cohort_level_promotion_does_not_crash_decisions` |

## 4. Decision quality

| # | Attack | Found | Fix | Pinned by |
|---|---|---|---|---|
| 22 | No true effects at all (null scenario) — does it still "find" winners? | 2 false winners in 16 experiments over two seeds: consistent with the ≤ 5 % bound (P ≈ 0.19 of ≥ 2), not proof; one was later rolled back by the holdout test | The audit then found the cohort family re-spent the look's α (real 2α bug) → 80/20 split | `reports/robustness.md`, `test_look_alpha_never_exceeds_total_over_any_sequence` |
| 23 | Winner whose effect has already faded | **H** — promoted on its whole-window lift | Stability check on disjoint windows before promotion; re-checked every tick while the approval is pending | `test_stability_blocks_winner_whose_recent_lift_vanished` |
| 24 | Winner's curse | **H** — a genuine winner rolled back because the promotion estimate was inflated | Decay tested against the promotion's 80 % LCB; both decay clauses at 1 % (hourly repeated looks) | `test_decay_not_triggered_by_winners_curse_shrinkage` |
| 25 | Decay on a small `next_campaign_only` workflow | **H** — never tested (holdout too thin; versions reset at promotion) | Adaptive 24–72 h window; earlier campaigns' concurrent calls kept; estimate stratified by config version (Simpson) | `test_decay_window_widens_for_thin_holdout` |
| 26 | Winner that only wins alongside a minor option of the other dimension | Not checked | Interaction check within the other dimension's dominant option | `test_interaction_blocks_a_winner_that_loses_where_it_will_run` |
| 27 | Caller ID flagged on an approval-only workflow | **C** — kept ~91 % of traffic for days ("unknown never moves traffic" also protected a measured-degraded number) | A degraded number always loses its share; emergencies only need the best-case approver latency | `test_did_target_degraded_number_always_loses_traffic_even_without_healthy` |
| 28 | Volume fatigue next to a fresh number | **H** — mistaken for a spam flag; 100 % of traffic put on one number (found by comparing crashed vs clean runs) | Degraded also requires a drop against the number's own history | `test_did_*` tests |
| 29 | Borderline-unsafe prompt (validation exactly at the threshold) | **H** — 20 h MTTR; a lucky validation vetoed a strong production signal | Pooled second validation within 1 SE; benefit of the doubt to safety once production flags fired | robustness r1/r2 MTTR 120–165 min |
| 30 | QA-flag false alarm on the production prompt | **H** (first version) — swapped in a "strict" script, engagement −14 % | Two-signal confirmation; engagement verification after any fix | public_02: `incident_not_confirmed` decision on the good prompt |
| 31 | Operational change silently damaging the guardrail KPI | **M** — no post-apply check for schedule / caller-ID / per-person changes | `post_apply_verification` 24 h after every applied change; breach → alert | `test_post_apply_verification_flags_a_guardrail_breach` |
| 32 | Low credits (12) with two prompt incidents | **H** — second incident never fixed | Validation size adapts to the balance; probe skipped when credits are scarce | robustness r5 |
| 33 | Winner that is already decaying when it wins (public_01 W3: decay onset D3, winner D4) | **M** — not rolled back by the end of the run, and the audit could not show whether the detector ran or what it could see. Measured: holdout ~150 connected calls/day; over D5–7 W3 − W1 = −0.013 (z −0.53), vs promotion LCB z −1.52. No evidence of decay in the data the run produced; lowering the 1 % threshold would bring back false rollbacks (#24) | No threshold change. Every passing decay check is audited daily (`decay_check`) with the smallest true drop each clause would catch with 80 % probability on its window (`detectable_drop_vs_promotion`, `detectable_negative_lift`) | `test_decay_not_triggered_by_noise_and_reports_what_it_could_detect` (the public_01 numbers), `test_genuine_decay_with_enough_holdout_is_rolled_back` |
| 34 | Bad prompt that hurts some variant options more than others (incident × variant) | Not analysed. The first version of the analysis, run over the robustness suite, then reported two interactions that the simulator's truth does not contain (hallucination depends only on the prompt): (a) W1's change was compared with "all other options", which were W3 before and W2 during a promotion; (b) a decaying winner's engagement drop looked like an interaction | Randomised difference-in-differences per option; the comparison group is only options with ≥ 150 connected calls in *both* windows; only the QA flag rate can raise an interaction (engagement reported, never flagged, because option effects drift on their own); Bonferroni across flag tests; recorded on every incident close; diagnostic only (the fix is workflow-wide). Re-run on the two stores: 0 interactions | `test_option_hit_harder_by_the_bad_prompt_is_detected`, `test_uniform_damage_is_not_an_interaction`, `test_thin_incident_is_reported_as_untestable_not_as_no_interaction`, `test_comparison_group_must_be_the_same_options_in_both_windows`, `test_engagement_change_of_one_option_is_reported_but_never_flagged` |
| 35 | Borderline-unsafe prompt (true 2.5 % hallucination vs 0.6 %) shipped when credits are low (robustness r5: 12 credits) | **H** — 51 h MTTR. The supervisor-prompt probe was skipped (needed ≥ 10 credits, 9 left); production flags fired a day later; a 100-call confirmation run with one failure (0.99) vetoed hundreds of production calls under the "≥ threshold + 1 SE" rule; then a 24 h quiet period | A validation may overrule a production alarm on a prompt changed in the last 3 days only if it *demonstrates* safety: the exact one-sided 95 % upper bound on its failure rate within the policy limit (`stats.validation_vetoes`) — the policy's `min_validation_pass_rate` is the approver's gate for prompt changes, so a validation that cannot show the prompt clears it with confidence does not overrule the production signal. One failure in 100 cannot show < 3 %; a clean 100-call run, or ≤ 3 failures in 300 (a good prompt passes this 89 % of the time), still can. A first version at 90 % still let 4/300 (0.987) veto a true-2.5 % prompt in the robustness suite (r1 seed 2: 50 h MTTR) The long-standing reference prompt keeps the 1-SE rule (a spike there is more often noise; attack #30). The probe now runs with ≥ 4 credits (1 credit at the low-credit size). A/B: {{AB35}} | `test_small_validation_cannot_overrule_a_production_alarm_on_a_fresh_prompt`, `test_fail_ucb_matches_exact_clopper_pearson` |
| 36 | A challenger dropped as significantly worse mid-experiment | **M** — the code renormalised the freed share across *all* live arms (13.3 % → 15.4 % for each remaining challenger), contradicting its own rule that harm stopping "only ever moves traffic back to the incumbent", and raising exposure to options not yet shown safe | The dropped share goes to the incumbent; each remaining challenger keeps its sample rate, so its test keeps its power and timeline | `test_dropped_share_goes_to_the_incumbent_not_to_other_challengers` |
| 37 | Pickup falls in the 24 h after a change to a lever heard only after connect (welcome, voice, prompt) | **L** — the post-apply check paged a guardrail breach (public_02 final run: pickup 0.261 → 0.240 after a voice change) that the change cannot have caused; before/after is time-confounded (campaign mix, hour, number health) | A pickup-guardrail breach after a post-connect-only change is recorded with the reason, not paged; real pickup problems still page through their own detectors with the cause attached. Breaches after schedule / caller-ID / cohort changes still page. Alerts now carry their reasoning | `test_pickup_drop_after_a_voice_change_is_recorded_but_not_paged`, `test_post_apply_verification_flags_a_guardrail_breach` |

## 5. What we tried and could not break

- Governance bypass: every config change in every run traced to an `APPLIED` proposal row (approval or
  policy-permitted auto route); 0 auto-apply attempts rejected by policy in the final runs.
- Business-owned settings: no code path writes cadence, dialling window or capacity (they are not in the config
  schema we send; hour weights are validated inside the dialling window by the simulator and by us).
- Pickup and engagement are never combined in any decision rule or report.

## 6. Known gaps (not fixed, stated)

- Credit-spending calls have no idempotency key in the API: a crash between sending a validation run and recording
  it can spend ≤ 3 credits twice (bounded; the ledger marks it `sent`).
- An open approval adopted after state loss is never applied (safe, but the approver's yes is wasted).
- Database interruption mid-transaction is covered by SQLite's atomic commit and by the corruption check at start;
  we did not inject disk-full errors.
