# Decision quality — what the controller should do, must not do, and how we check it

Unit tests prove functions behave; this table states the **behaviour** we expect in 20 adversarial situations, the
behaviour that is **forbidden**, the **audit evidence** a reviewer should find, and the tests that enforce it. Where an
exact number cannot be known in advance, the criterion is an invariant, not a value. All tests use only API-shaped
observations (call rows, config versions, approvals) — never simulator internals.

| # | situation | expected | forbidden | audit evidence | enforced by |
|---|---|---|---|---|---|
| 1 | Pickup falls, engagement stable | caller-ID / schedule response only | touching welcome / voice / prompt for a pickup problem; a pickup alert after a post-connect change | `did_health` with windows; `auto_apply` caller_id | `test_did_health_degraded_healthy_unknown`, `test_engagement_changes_never_move_caller_id_health`, `test_pickup_drop_after_a_voice_change_is_recorded_but_not_paged` |
| 2 | Engagement falls, pickup stable | KPI-drift alert; experiments / incidents judge engagement | moving caller IDs | `alert` (KPI drift) | `test_kpi_drift_alerts_on_real_drop_only`, `test_did_health_equal_pickup_is_healthy_not_degraded` |
| 3 | Both fall | both KPIs reported separately, never blended | a combined score driving a change | `alert` lists each KPI | `test_kpi_drift_alerts_on_real_drop_only` |
| 4 | Temporary fluctuation looks like degradation | no action | a change from one bad hour or a few calls | none (no decision) | `test_did_health_small_noisy_dip_is_not_degraded`, `test_halluc_spike_quiet_on_baseline_noise`, `test_halluc_spike_needs_population_not_anecdotes` |
| 5 | Population composition changes | no winner from the shift | a winner created by mix moving for everyone | look evidence: arms tie | `test_population_shift_applied_to_every_arm_creates_no_winner`, per-version stratification in `decay_check` |
| 6 | Baseline drifts | no winner from the drift | a winner from time trends | look evidence | `test_baseline_drift_shared_by_all_arms_creates_no_winner` |
| 7 | A small cohort looks like a winner | cohort-level winners need Bonferroni across cohorts on their own alpha share; small groups merged | promoting on a thin cohort | `cohort_check` in winner evidence | `test_bootstrap_merges_small_groups_to_min_share`, `test_look_alpha_never_exceeds_total_over_any_sequence` |
| 8 | Several variants look promising | Holm step-down; highest 80 % LCB among significant | choosing by raw point estimate across many arms | `Holm (...)` line in `decision <id>` | `test_holm_*`, `test_clear_winner_promoted_deterministically` |
| 9 | Insufficient evidence | keep looking, then keep the incumbent | an invented winner | `experiment_look … continue`, `experiment_no_winner` | `test_insufficient_sample_no_action`, `test_no_difference_at_horizon_keeps_incumbent`, `test_more_data_with_no_difference_never_buys_a_winner` |
| 10 | A winner loses its advantage | withdraw a pending promotion; roll back a promoted one | promoting a faded effect | `promotion_withdrawn`, `decay_check` → `decay_detected` | `test_stability_blocks_winner_whose_recent_lift_vanished`, `test_decay_detected_when_lift_collapses`, `test_genuine_decay_with_enough_holdout_is_rolled_back` |
| 11 | Supervisor changes the prompt mid-experiment | lock 48 h; probe the prompt; experiments continue on new versions | overwriting the edit | `supervisor_edit`, `validation_run` (probe) | `test_supervisor_edit_between_approval_and_apply_is_never_overwritten`, `test_design_starts_when_live_and_supervisor_edit_aborts` |
| 12 | Caller ID changes during measurement | experiment continues; analysis per config version | mixing versions with different allocations | `versions` in the experiment | `test_evidence_only_from_experiment_versions`, `test_design_starts_when_live_and_supervisor_edit_aborts` |
| 13 | An event arrives late | processed in event order; the workflow holds decisions while events are pending | deciding on a view that misses a supervisor edit | `hold` while inbox pending | `test_supervisor_event_survives_a_transient_failure_and_holds_decisions` |
| 14 | Duplicate delivery | counted once | double-counting | `verify`: calls unique per event | `test_ingest_all_and_idempotent_replay`, `test_rollups_equal_raw_aggregation_and_survive_replay`, `test_partial_chunk_is_rolled_back_and_reread_whole` |
| 15 | Restart during an experiment | same experiment continues under the same id | a duplicate design or a lost look | crash report check 16 | `test_kill_twice_restart_finishes_without_duplicates`, `reports/crash_recovery.md` |
| 16 | An approval becomes stale | `STALE`, re-plan on the new base | applying over a newer base | `proposal_stale` | `test_stale_at_apply_never_calls_apply`, `test_stale_reported_by_apply_endpoint` |
| 17 | Config changes outside the controller | treated as a supervisor edit: locked, acknowledged | a later proposal undoing it | `verify`: every supervisor edit acknowledged | `test_supervisor_edit_between_approval_and_apply_is_never_overwritten`, `test_verify` (unacknowledged edit = INVALID) |
| 18 | A harmful experiment | arm dropped back to the incumbent; harm blacklist | spreading its traffic to other unproven arms | `experiment_drop_arm` | `test_harmful_challenger_dropped_before_horizon`, `test_dropped_share_goes_to_the_incumbent_not_to_other_challengers` |
| 19 | The best decision is to do nothing | no proposal; or `experiment_skipped` with the evidence | a request with no change; a re-test with nothing to learn | `experiment_skipped` | `test_no_change_no_request`, `test_step_experiments_skips_a_retest_of_a_supervisor_choice_with_nothing_to_learn` |
| 20 | Two changes interact | a winner must still win alongside the other dimension's main option | promoting a winner that only wins next to a minor option | `interaction` in winner evidence | `test_interaction_blocks_a_winner_that_loses_where_it_will_run` |

## Checking a real run

```bash
python -m outcomeloop --db state/public_02_incidents.db verify          # 11 integrity checks
python -m outcomeloop --db state/public_01_dev.db replay <winner id>     # recount the look from raw calls
python scripts/evaluate.py                                               # fresh runs + tests + verify, one command
```

`replay` recomputes an experiment look from the raw `calls` rows (not the rollups the controller read) and re-runs
the caller-ID detector as of the decision; disagreement with the stored evidence is reported as INVALID.
