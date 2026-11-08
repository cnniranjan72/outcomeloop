# OutcomeLoop — reviewer evidence package (20 minutes)

Everything here is generated from the final runs by `scripts/build_evidence.py` (real command output; the first line
of each file is the command). Numbers live in [`RESULTS.md`](RESULTS.md), each with its source report and marked
**measured** or **projected**.

## Minutes 0–5 · what it is and whether it works

1. [`RESULTS.md`](RESULTS.md) — scenario outcomes, load, memory, scaling, robustness, crash recovery, tests.
2. [`../README.md`](../README.md) — the architecture diagram and the module map.
3. One-line design: a single synchronous loop (ingest → decide per workflow → govern → advance) over one SQLite store;
   every change to the world goes through governance; every decision is a row with its evidence and reasoning.

## Minutes 5–12 · follow one change end to end

The eight questions a reviewer asks, answered from the controller's own store:

| question | where to look |
|---|---|
| 1. What did the controller observe? | `status_public02.txt`; per decision, the `evidence` block in `decision_*.txt` |
| 2. What degradation did it detect? | `lifecycle_caller_id_public02.txt` (degraded caller ID), `lifecycle_incident_public02.txt` (unsafe prompt) |
| 3. Why did it investigate? | the `Why:` line of every decision (`decision_incident_opened_public02.txt`) |
| 4. Which experiment did it select? | `lifecycle_experiment_public01.txt`, first lines: design, planned n, minimum detectable effect |
| 5. What evidence determined the result? | the same file: every daily look (lift, z, p, n), then the winner's Holm / guardrail / cohort / stability / interaction checks |
| 6. What approval was obtained? | `proposal_approved` lines: approval id, request and decision times |
| 7. What change was applied? | `proposal_applied` lines: the live config version |
| 8. What happened afterwards? | `post_apply_verification` (24 h before/after), daily `decay_check`, `decay_detected` → rollback |

Reproduce any of them on a store:

```bash
export PYTHONPATH=src
python -m outcomeloop --db state/public_01_dev.db audit --wf nw_renewal --kind "experiment_*"   # find a story
python -m outcomeloop --db state/public_01_dev.db lifecycle <experiment id>                   # the whole story
python -m outcomeloop --db state/public_02_incidents.db decision <id>                         # one row, fully
python -m outcomeloop --db state/public_02_incidents.db why ks_cancel --at "D3 13:00"         # one config version
python -m outcomeloop --db state/public_02_incidents.db customer ks_cancel:p<id>              # one person
```

## Minutes 12–17 · would it survive production?

| claim | evidence |
|---|---|
| crash-safe: kill at any point, no double apply, no lost approval | `../reports/crash_recovery.md` (9 SIGKILLs, 20 checks); `tests/unit/test_adversarial.py` apply-boundary matrix |
| exactly-once ingestion | chunk rows + checkpoint in one transaction; crash check 9 (`SUM(chunks.events) == last_event_id`) |
| statistics do not invent winners | 0 false winners on the no-effects scenario (`../reports/robustness.md`); alpha spent as an explicit budget |
| generalises beyond the public truth | 7 generated scenarios × 2 seeds (`../reports/robustness.md`, `../docs/submission/ROBUST_NOTES.md`) |
| keeps up at load; where 10× breaks | `../reports/public_03.md`, `../reports/scaling.md` (measured 1× / 3×, projected 10×, sharding prototype) |
| memory | `../reports/memory.md` (cause found and fixed: 1,046 → 360 MB) |
| what we attacked and what broke | `../docs/ADVERSARIAL_TESTING.md` (each attack, what it found, the fix, the test) |

## Minutes 17–20 · judgement

- Scope, stakeholder replies and wrong assumptions in the memos: `../SUBMISSION.md` §2–§4.
- What we cut, what we would do next, and the limitations we know about: SUBMISSION.md §13, ADVERSARIAL_TESTING §6.

## Rebuild this package

```bash
scripts/run_scenario.sh public_01_dev && scripts/run_scenario.sh public_02_incidents   # final stores + grades
python scripts/build_evidence.py
```
