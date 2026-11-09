# Final submission readiness

## Completed requirements (assignment §6 floor and §8 deliverables)

| requirement | status | evidence |
|---|---|---|
| `./run.sh <SIM_URL>` runs to the end, no manual steps | done | every `reports/*` run; Linux container: `scripts/docker_scenario.sh` |
| public_01 and public_02 end to end | done | `reports/public_01_dev.md`, `reports/public_02_incidents.md` (reproduced byte-identically by a fresh run) |
| audit trail (C12) | done | `decisions` (append-only triggers); `why`, `decision`, `lifecycle`, `customer`, `audit` |
| constraints never broken | done | governance boundary only path (crash check 3); supervisor edits locked, never overwritten; pickup/engagement separate; LLM never decides; populations only |
| SUBMISSION.md complete | done | built by `scripts/build_submission.py` (no placeholders); consistency pass in `6155ba3` |
| reports for public_01/02 + load numbers for public_03 | done | `reports/` |
| crash-recovery evidence | done, on the final code | `reports/crash_recovery.md` (commit `6155ba3`: 9 hard kills, 20 checks, 0 failed) |
| commit history | done | small commits, each with its evidence |
| walkthrough video (optional) | done | `walkthrough.mp4` (4:44, real VS Code / GitHub / terminal footage, narrated); added to the repository at the final push |

## Verified evidence (current)

`reports/EVALUATION.md` — `scripts/evaluate.py --slow` on commit `6155ba3`: tests 256 passed (254 unit + 2 slow);
public_01 +15.3 % / 0 harmful of 26; public_02 +25.3 % / 2 harmful of 27 / MTTR 105 min (detection 15 min, the rest
approver latency); both stores `verify` 11/11 VALID. The fresh public_01/02 grade reports are byte-identical to the
committed ones (`git diff` empty), so the reports correspond to the current code.

`reports/crash_recovery.md` — commit `6155ba3`: PASS, 20 checks (19 PASS, 1 INFO, 0 FAIL); outcome under 9 kills
+26.9 % vs +25.3 % uninterrupted.

`evidence/RESULTS.md`: robustness 16/16; 0 false winners on the null scenario; peak memory 360 MB; 49 s per simulated
day at 1× in the grader-sized container; ≈ 460 s *projected* at 10×.

## Outstanding work

- The robustness suite (`reports/robustness.md`) is from `6ee64e0`, before the determinism fix (`b99b660`), which
  changes the order of simulator draws but no decision rule. A re-run takes 1–2 h and was stopped once by the host
  running low on memory: `MAX_PARALLEL=2 SEED_REPLICAS=2 scripts/robustness.sh` when the machine is free.
- The public_03 load figures were not re-run in the final review (`scripts/evaluate.py --load`, ~10 min); the code
  changes since (`947d858`, `c61962e`) touch proposal text and CLI output only.

## Known limitations

See `SUBMISSION.md` §13 (16 items). The ones a reviewer is most likely to probe:

1. A small, late decay may not be rolled back before a run ends (power; audited daily with what it could detect).
2. 10× is projected; ingest is single-core; sharding is a measured prototype, not wired into `run.sh`.
3. Calls are treated as independent observations (retries hit the same person): standard errors are optimistic.
4. Policies are read once at startup and not re-checked against a pending approval at apply time.
5. Credit-spending API calls have no idempotency key: a crash can double-spend ≤ 3 credits.
6. First-launch exploration costs show as "harmful" verdicts when a challenger is worse in truth.
7. Borderline prompts with very low credits or strict policy can take a day (r2, r5).
8. Two controllers started at the same time from one checkout need separate `OUTCOMELOOP_DB` values.

## Reviewer instructions

Start at `evidence/README.md` (20-minute path), then `SUBMISSION.md` (ten-minute read path at its top). Reproduce:

```bash
pip install -r requirements.txt
python scripts/evaluate.py          # tests + public_01 + public_02 from fresh runs, graded and verified
```

or by hand:

```bash
python -m sim baseline --scenario scenarios/public_02_incidents.yaml --run-dir runs/base02
python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/mine02 &
OUTCOMELOOP_DB=state/p02.db ./run.sh http://127.0.0.1:8700
python -m sim grade --run runs/mine02 --baseline runs/base02
PYTHONPATH=src python -m outcomeloop --db state/p02.db lifecycle <id from: audit --kind "incident_*">
```

## Final submission checklist

- [x] tests: `OUTCOMELOOP_SLOW=1 python -m pytest -q` all pass (256)
- [x] public_01 / public_02 final runs and grades committed; reproduced byte-identically on `6155ba3`
- [x] crash recovery on the final code (`6155ba3`)
- [ ] robustness suite on the final code (from `6ee64e0`; see Outstanding work)
- [x] SUBMISSION.md rebuilt, no placeholders, internally consistent; name and hours filled
- [x] evidence/ regenerated from the final stores
- [x] no interview-prep files in the repository; no co-author trailers
- [ ] `walkthrough.mp4` committed in the final push (author)
- [ ] reviewer added to the private GitHub repository (author)
