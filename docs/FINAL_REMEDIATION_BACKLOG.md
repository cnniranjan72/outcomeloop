# Final remediation backlog

From an independent review of commit `29987b6` against the original assignment (`git show aade79d:README.md`),
the memos and the simulator contract. Each finding was reproduced before it was fixed; each fix has a regression test
that fails on the old code, and the evidence was regenerated on the fixed commit (`6155ba3`).

Priorities: **P0** submission blocker · **P1** high-value correction · **P2** useful improvement · **P3** cosmetic.

No P0 was found: public_01 and public_02 run end to end with no manual steps, the audit trail is complete, no
constraint is broken, and SUBMISSION.md is complete.

| # | Pri | Finding (reproduced) | Root cause | Fix | Test | Status |
|---|---|---|---|---|---|---|
| 1 | P1 | public_02: the `nw_renewal` rollback was rejected (D5 16:10) and re-requested 50 min later; nothing in the audit store said a rejection was overridden or why | urgent requests skip the rejection cool-down in `Governance.can_request`, silently | the request's rationale opens with "Re-request: … rejected at …; sent again within the cool-down because …"; `proposal_submitted` carries `evidence.after_rejection`. Outcome-neutral (the simulator's approver is seeded by proposal id) | `test_urgent_request_inside_rejection_cooldown_says_it_is_a_re_request`, `test_routine_request_respects_rejection_cooldown…` | fixed `947d858` |
| 2 | P1 | `python -m outcomeloop why … \| Select-String` (or `> file`) crashed with `UnicodeEncodeError` on Windows | piped stdout uses the ANSI code page; the views print arrows | `main()` writes UTF-8 with replacement | `test_cli_output_survives_a_non_utf8_pipe` | fixed `c61962e` |
| 3 | P1 | SUBMISSION.md contradicted itself and the reports: C15 "not built" / "cut" vs "Built (minimal)"; "six" scenarios vs seven; "10× breaks at decision queries, then the writer" vs measured "ingest CPU first"; to-dos for features that exist (rollups, interaction check); "random kills" vs nine targeted kills; a generated measurement string pasted into stakeholder replies | ~30 string patches in the generator over stale source text | sources fixed, one plain scale sentence for replies, generator's 10× text corrected; ten-minute read path added | generator: no unfilled placeholders; manual diff review | fixed `6155ba3` |
| 4 | P1 | crash-recovery evidence was from `1c12251`, before the determinism fix | not re-run after later commits | re-run on `6155ba3`: PASS, 20 checks, 0 failed | `scripts/crash_recovery.sh` | fixed (this commit) |
| 5 | P2 | README "Setup" at line 1,056; no quick start | growth of the README | quick start below the headline table | — | fixed `6155ba3` |
| 6 | P2 | calls treated as independent; retries dial the same person, so SEs are optimistic | binomial per-call z-tests | documented (SUBMISSION §13.11); next: person-clustered SEs | null scenario: 0 false winners in 12 (empirical) | documented |
| 7 | P2 | policies read once; an approval granted before a policy change would still be applied | `_apply` checks config version, not policy | documented (§13.15); next: hourly policy reload + pre-apply policy check | — | documented |
| 8 | P2 | decisions not gated on ingest lag | unnecessary in the simulator (clock waits) | documented (§13.16); lag is measured and pages after 30 min | — | documented |
| 9 | P2 | two controllers started together from one checkout share the default state file; the second exits 3 | one-controller-per-file lock (intended) | documented in `run.sh` header and §13.14 | `InstanceLock` tests | documented |
| 10 | P2 | robustness report predates the determinism fix (`6ee64e0`) | re-run memory-killed once | documented in readiness; re-run when the host is free | `scripts/robustness.sh` | open |
| 11 | P3 | unused imports / locals / f-strings without placeholders | — | cleaned in `src/` (pyflakes clean); `scripts/` left | pyflakes | fixed in `src/` |
| 12 | P3 | `controller.py` ~1,650 lines (`detect_halluc` ~180) | decision steps grew in one class | not refactored now: regression risk outweighs benefit at submission time; split per capability is the next refactor | — | deferred |

Known costs that are not defects (measured, documented): the first-launch exploration on `nw_kyc` is marked harmful
when a challenger is worse in truth (8 of 16 robustness runs); borderline-unsafe prompts in low-credit or strict-policy
scenarios took 23–27 h (the one candidate fix, "heightened watch", was A/B-tested and showed no benefit).

## Second review (after the fixes)

- Diff of `947d858` re-read: both call sites that mark a workflow urgent outside caller-ID are decay rollbacks
  (`controller.py` decay check and `route`), so the new rationale is accurate in every case; the cool-down query uses
  the same window as `can_request`.
- Full suite 256 passed; public_01/02 grade reports byte-identical to before (the fix is outcome-neutral, as designed);
  both stores verify 11/11 VALID; crash recovery PASS on `6155ba3`.
- The public_02 store now shows the re-request explicitly (decision #230, proposal `ol-nw_renewal-8220-29`,
  `evidence.after_rejection`).
