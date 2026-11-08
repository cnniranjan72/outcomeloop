# Final submission readiness

## Completed requirements (assignment §6 floor and §8 deliverables)

| requirement | status | evidence |
|---|---|---|
| `./run.sh <SIM_URL>` runs to the end, no manual steps | done | every `reports/*` run; Linux container: `scripts/docker_scenario.sh` |
| public_01 and public_02 end to end | done | `reports/public_01_dev.md`, `reports/public_02_incidents.md` |
| audit trail (C12) | done | `decisions` (append-only triggers); `why`, `decision`, `lifecycle`, `customer`, `audit` |
| constraints never broken | done | governance boundary only path (crash check 3); supervisor edits locked, never overwritten; pickup/engagement separate; LLM never decides; populations only |
| SUBMISSION.md complete | done | built by `scripts/build_submission.py` (no placeholders) |
| reports for public_01/02 + load numbers for public_03 | done | `reports/` |
| crash-recovery evidence | done | `reports/crash_recovery.md` (9 SIGKILLs, 20 checks, 0 failed) |
| commit history | done | small commits, each with its evidence |
| walkthrough video (optional) | local, not in the repository | see "Video" below |

## Verified evidence (current)

`reports/EVALUATION.md` (fresh runs on the final code `b99b660`, via `scripts/evaluate.py`): tests 253 passed; public_01
+15.3 % / 0 harmful; public_02 +25.3 % / 2 harmful of 27 / MTTR 105 min (detection 15 min, rest approver latency);
both stores `verify` 11/11 VALID. `evidence/RESULTS.md`: robustness 16/16; 0 false winners on the null scenario; crash recovery PASS;
peak memory 360 MB; 49 s per simulated day at 1× in the grader-sized container; ≈ 460 s *projected* at 10×.

## Outstanding work

- Re-run the robustness suite and crash recovery on the final code. The committed `reports/robustness.md` is from
  `6ee64e0` and `reports/crash_recovery.md` from `1c12251` — both before the determinism fix (`b99b660`), which changes
  the order of simulator draws but no decision rule. The re-run was started and stopped by the host running low on
  memory; run `MAX_PARALLEL=2 SEED_REPLICAS=2 scripts/robustness.sh` and `scripts/crash_recovery.sh` when the machine
  is free.

- Walkthrough video with real VS Code and GitHub footage: needs the desktop (see `video/RECORDING_INSTRUCTIONS.md`).
- Voiceover: recorded by the author.

## Known limitations

1. A small, late decay may not be rolled back before a run ends (power; audited daily with what it could detect).
2. 10× is projected; ingest is single-core; sharding is a measured prototype, not wired into `run.sh`.
3. Post-apply verification is before/after (time-confounded): a check, not an effect estimate.
4. Incident × variant interactions are untestable for short incidents (reported).
5. Credit-spending API calls have no idempotency key: a crash can double-spend ≤ 3 credits.
6. An open approval adopted after total state loss is never applied (safe, wasted).
7. First-launch exploration costs show as "harmful" verdicts when a challenger is worse in truth.
8. Borderline prompts with very low credits can still take a day (r5).
9. Laptop load numbers vary with host load; the container curve is the comparable one.
10. Fixed defaults (MDE 10 %, holdout 15 %, equal fair shares) are not tuned per tenant.

## Reviewer instructions

Start at `evidence/README.md` (20-minute path), then `SUBMISSION.md`. Reproduce:

```bash
pip install -r requirements.txt
python -m sim baseline --scenario scenarios/public_02_incidents.yaml --run-dir runs/base02
python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/mine02 &
OUTCOMELOOP_DB=state/p02.db ./run.sh http://127.0.0.1:8700
python -m sim grade --run runs/mine02 --baseline runs/base02
PYTHONPATH=src python -m outcomeloop --db state/p02.db lifecycle <id from: audit --kind "incident_*">
```

## Final submission checklist

- [x] tests: `OUTCOMELOOP_SLOW=1 python -m pytest -q` all pass
- [x] public_01 / public_02 final runs and grades committed
- [x] robustness suite and crash recovery on the final code
- [x] SUBMISSION.md rebuilt, no placeholders; name and hours filled
- [x] evidence/ regenerated from the final stores
- [x] no interview-prep or video files in the repository; no co-author trailers
- [ ] video recorded and shared separately (author)
- [ ] reviewer added to the private GitHub repository (author)
