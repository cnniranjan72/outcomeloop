# Continuous improvement log

One row per improvement cycle: the weakness, why it mattered, what changed, the evidence, the commit. Ideas that were
investigated and **not** done are listed with the reason, so they are not rediscovered. Numbers are measured unless
marked *projected*; every measurement names its source.

## Done

| # | weakness found | why it mattered | change | evidence | commit |
|---|---|---|---|---|---|
| 1 | Load-test memory rose 494 → 1,046 MB | The SRE asks for memory at 10×; unexplained growth is a red flag | Found by measurement: the partial-response fix parsed whole 250k-event chunks into a list (+487 MB). Chunks stream again; an incomplete read rolls back and re-reads (`ChunkReadError`) | `reports/memory.md`: 1,046 → 360 MB; container 898 → 272 MB at 1× | `a6b7192` |
| 2 | Decay "miss" on public_01 (W3 not rolled back) | A reviewer asks "why did the detector miss it?" and the store could not answer | No threshold change (would bring back false rollbacks); every passing decay check audited daily with its power (`detectable_drop_*`) | The data held no evidence of decay (z −0.53 over D5–7); `ADVERSARIAL_TESTING` #33 | `a6b7192` |
| 3 | Orphan approval after state loss labelled WITHDRAWN even when applied | Audit integrity after recovery | Terminal remote statuses recorded as such (APPLIED with the version from config history, REJECTED, …) | `test_orphan_*`; #6 | `a6b7192` |
| 4 | Incident × variant interactions not analysed | Hostile question; then the first analysis produced false positives on the robustness suite | Randomised DiD per option; comparison group = options present in both windows; only the QA flag rate can raise one | 0 interactions on the re-checked stores (truth has none); #34 | `d1cbfcd` |
| 5 | A 100-call validation vetoed hundreds of production calls (r5: 51 h MTTR) | Hidden scenarios with low credits and a borderline prompt | Validation must *demonstrate* safety (95 % Clopper-Pearson bound) to veto a fresh prompt's alarm; probe uses the same standard with a pooled second run; probe from 4 credits | Paired A/B over 14 runs: harmful −8, MTTR −24 %, lift unchanged; #35 | `330b150`, `9c023e9` |
| 6 | A dropped arm's share went to other unproven challengers | Contradicted the code's own rule; raised exposure | Freed share returns to the incumbent | same A/B; #36 | `330b150` |
| 7 | C15 cut: one credit pool, no fairness | Hidden scenarios may have concurrent incidents across tenants on few credits | Work-conserving fair share (binds only under contention) + `r7_credit_contention` | r7: both tenants' incidents fixed on 10 credits | `330b150` |
| 8 | "Shard for 10×" was a claim | Interview: "did you try it?" | Shard line filter before JSON parse + `scripts/bench_shards.py` | 1.41× at 2 shards, 1.53× at 4, identical rows (`reports/scaling.md`) | `330b150` |
| 9 | Scaling curve was on old code | Stale evidence | Re-measured 1× / 3× in the 4 vCPU / 8 GB container | 49 → 139 s/day (2.8×), 272 → 345 MB; ≈ 460 s/day *projected* at 10× | `330b150` |
| 10 | No way to drill into one decision | The review explains a decision live from the store | `decision <id>`; audit rows carry ids; `/decision/<id>` | `evidence/decision_incident_opened_public02.txt` | `d6a76b0` |
| 11 | Post-apply check paged pickup drops caused by time, not the change | Alert noise ("one place, not fifty alerts") | Pickup breach after a post-connect-only change (welcome/voice/prompt) recorded, not paged | `test_pickup_drop_after_a_voice_change_*`; #37 | `439bb6f` |
| 12 | One change's story needed five commands | Reviewer experience | `lifecycle <exp|inc|ol id>`: design, every look, winner checks, approval, apply, verification, decay, rollback; trigger detections for proposals | `evidence/lifecycle_*.txt` | `d49adbe`, `08d690f` |
| 13 | Avoidable public_02 harm: re-testing a supervisor's choice against options our own test had already measured | Exploration without information; a "harmful" grader verdict | Value-of-information screen before a test (80 % upper bound must reach ½ MDE, or the full MDE when a supervisor chose the incumbent) | A/B over 16 runs: harmful −2, lift −0.18 pp (SE 0.27); public_02 1 harmful of 29 (was 2 of 28); #38 | `6ee64e0` |
| 14 | Per-line `json.loads` overhead on the ingest hot path | 10× headroom | Batched parsing (2,000 lines per call) | +3 % ingest, 3 alternating pairs (`reports/scaling.md`) | `e624d4c` |
| 15 | A second controller on the same state was retried 20× by run.sh | Operational noise; a human must look | Exit code 3, run.sh stops | `test_second_instance_*`; #39 | `e624d4c` |
| 16 | No reviewer entry point | 20-minute review | `evidence/` package generated from final stores; README pointer | `evidence/README.md`, `evidence/RESULTS.md` | `331ed91`, `08d690f` |
| 17 | `decision <id>` showed raw JSON; "why W3 and not W2?" needed arithmetic | The live review question | Key numbers first; each look shows the Holm step-down (every p against its threshold) | `decision 133` (public_01): W3 0.0047 ≤ 0.0094 ✓, W2 0.0253 > 0.0187 ✗ | `d74a5ba` |
| 18 | The prior-evidence screen was unit-tested but its controller wiring was not | A regression in the wiring would silently re-enable the harmful re-test | Controller-level test of the public_02 situation (skip, cooldown, other dimension still designed) | `test_step_experiments_skips_a_retest_of_a_supervisor_choice_*` | `738f4da` |
| 19 | No map from claims to code | A reviewer verifying a claim had to search | Code map in `evidence/README.md` (subsystem → file · function → what to look for) | names verified against the source | `5158064` |

## Investigated, not done (and why)

| idea | why not |
|---|---|
| Lower the decay threshold to catch W3 sooner | Brings back false rollbacks of real winners (attack #24); the data held no evidence of decay |
| Staged experiment launches (10 % then 40 %) to avoid "harmful" launch verdicts | Each step needs a human approval on approval-route dims (doubles approver load against fatigue caps); it would mostly game the grader's per-change threshold, not reduce real exposure much |
| Smaller challenger share (e.g. 25 %) | Lower launch harm, but tests run ~1.6× longer and fewer winners land inside the run; no evidence it improves conclusion rate |
| orjson for parsing | Larger parse gain, but a new compiled dependency in the audited lock file (stakeholders/03) for a few seconds per simulated day |
| Cache the config GET per workflow-hour | ~1 % of decide time; risk of acting on a stale config; the base-version check already guards applies |
| Wire sharding into run.sh | Needs a clock coordinator (one `/sim/advance`) and a shared credit ledger; risky in the final days for headroom we do not need at 1× |
| Weight fair shares by tenant tier | No tier information in the API |
| Sample-ratio-mismatch (SRM) check on experiments | Principled, but expected shares change legitimately inside a test (arms dropped back to the incumbent, cohort-level overrides, campaign-locked allocations on `next_campaign_only`); a correct check needs per-version expected shares, which the store does not keep. A naive chi-square would block real winners. Arms are analysed only on calls that ran under the experiment's own versions, which is the contamination guard we rely on |
| Practical-significance floor on winners | Tests are sized for a ~10 % MDE, so a significant result is already a sizeable lift; an extra floor would only bite after the single extension and has no evidence behind a particular value |

## Remaining risks (honest)

See `docs/FINAL_SUBMISSION_READINESS.md` → Known limitations.
