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
| 6 | Approval exists remotely with no local row (state lost / rebuilt) | **M** — only logged; it would never be counted toward the approver's budget | Adopted as `WITHDRAWN` (no context → never applied) with its real creation time | `test_orphan_approval_without_local_context_is_never_applied` |
| 7 | Auto-apply refused (403) | **M** — retried hourly forever; the ramp could overshoot `max_shift` by rounding | A 403 sends the dims to the approval route for 24 h; ramp steps keep a margin and are re-checked after canonicalisation | audit fix, `test_auto_apply_ramps_within_max_shift`, `test_ramp_steps_are_at_least_an_hour_apart` |
| 8 | Supervisor-set caller ID after the 48 h lock | **M** — silently re-spread by auto-apply | A dimension a supervisor set is approval-only until one of our approved changes to it lands | audit fix |

## 2. Event processing

| # | Attack | Found | Fix | Pinned by |
|---|---|---|---|---|
| 9 | Same chunk ingested twice, incl. with its checkpoint deleted | Rows held (`INSERT OR IGNORE`); **H** new hourly rollups would have double-counted | Rollups are recomputed per touched workflow-hour from the stored rows — a pure function, replay-safe by construction | `test_ingest_all_and_idempotent_replay`, `test_rollups_equal_raw_aggregation_and_survive_replay` |
| 10 | Exception mid-chunk | **H** — in-memory code/feature caches kept values from the rolled-back transaction | Caches rebuilt on rollback | `test_ingest.py` atomicity tests |
| 11 | Transient simulator error while handling a supervisor `config_changed` event | **H** — event marked done, supervisor lock never written; next plan would overwrite the edit | Events retried, never dropped (dead-letter after 10); the workflow gets no decisions while it has unprocessed events | `test_supervisor_event_survives_a_transient_failure_and_holds_decisions` |
| 12 | Truncated / malformed chunk response | **M** — `ValueError` outside the retry loop → crash-loop | Chunks fetched and parsed as a unit, re-fetched whole on a partial response | `test_truncated_chunk_is_refetched_whole_never_half_ingested` |
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

## 5. What we tried and could not break

- Governance bypass: every config change in every run traced to an `APPLIED` proposal row (approval or
  policy-permitted auto route); 0 auto-apply attempts rejected by policy in the final runs.
- Business-owned settings: no code path writes cadence, dialling window or capacity (they are not in the config
  schema we send; hour weights are validated inside the dialling window by the simulator and by us).
- Pickup and engagement are never combined in any decision rule or report.

## 6. Known gaps (not fixed, stated)

- Credit-spending calls have no idempotency key in the API: a crash between sending a validation run and recording
  it can spend ≤ 3 credits twice (bounded; the ledger marks it `sent`).
- An approval adopted after state loss is never applied (safe, but the approver's yes is wasted).
- Database interruption mid-transaction is covered by SQLite's atomic commit and by the corruption check at start;
  we did not inject disk-full errors.
