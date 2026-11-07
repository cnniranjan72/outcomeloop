# Crash-recovery evidence — public_02_incidents

**Result: PASS (20 checks: 19 PASS, 1 INFO, 0 FAIL).** The controller was hard-killed 9 times (subprocess.Popen.kill() (SIGKILL on POSIX, TerminateProcess on Windows)) during one run of public_02 and restarted against the same SQLite file each time; the final launch ran the scenario to the end. Code: commit `43dcd70` (final). Platform: win32, Python 3.12.10. Run started 2026-11-07T17:01:27.485+05:30.

Every number below comes from `reports/crash_recovery_timeline.json` (written by `scripts/crash_recovery.py`) and the controller's own audit store `state/crash_public_02.db`. A graceful shutdown is never used.

## 1. Method

`scripts/crash_recovery.py` (wrapper: `scripts/crash_recovery.sh`) uses only the standard library and works on
Linux and Windows.

1. It starts `python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/crash_public_02
   --port 8711 --force` and waits for `/health`. It also deletes `state/crash_public_02.db*` so the DB starts
   fresh.
2. It launches `python -m outcomeloop run --url http://127.0.0.1:8711` with `PYTHONPATH=src`,
   `OUTCOMELOOP_DB=state/crash_public_02.db` and `PYTHONUTF8=1`.
3. It watches two things:
   * the controller's SQLite store, opened **read-only** (`mode=ro`) and polled every 1 ms;
   * the simulator's public API, polled by a background thread (`/sim/state`, plus `/approvals?status=approved`
     for kill d). The thread is needed because the simulator serialises requests, so an API poll blocks during
     the controller's `/sim/advance`. The DB poll must never wait for it.
4. When a kill's trigger fires, it calls **`Popen.kill()`** on the PID it launched. That is SIGKILL on Linux and
   TerminateProcess on Windows: no signal handler, no `finally`, no atexit. It never kills by image name.
5. After each kill it snapshots the DB (counts plus in-flight rows) and the sim state into the timeline, then
   relaunches.
6. If a targeted kill lands just after the targeted state has already moved on (`landed_on_target_state=false`),
   it retries the same target on the next launch (bounded attempts).
7. After the last kill it lets the controller finish. It then runs `scripts/verify_recovery.py` while the
   simulator is still up (the API cross-checks need it) and stops only the simulator PID it started.

## 2. Kill schedule (final run)

| # | aim | sim time at kill | what was in flight (from our DB, read-only) | DB state right after the kill |
|---|---|---|---|---|
| 1 (a) | during history ingestion | D0 00:00 | history backlog ingestion in progress: workflows registered, 0 chunks committed, 1.0s into ingest (2.2s after launch) | chunks 0, calls 0, decisions 0, proposals {}, credit calls in flight 0 |
| 2 (c) | while a proposal is PENDING | D0 10:00 | proposal ol-nw_renewal-600-3 is PENDING (approval apr_00001) | chunks 7, calls 141,732, decisions 22, proposals {'APPLIED': 2, 'PENDING': 1}, credit calls in flight 0 |
| 3 (d) | approval APPROVED/APPLYING (approved, not yet applied) | D0 12:00 | approval apr_00003 (ol-ks_cancel-660-5) is 'approved' at the simulator, our row still PENDING (not yet applied) | chunks 15, calls 143,532, decisions 26, proposals {'APPLIED': 2, 'PENDING': 3}, credit calls in flight 0 |
| 4 (d) | approval APPROVED/APPLYING (approved, not yet applied) | D0 12:15 | approval apr_00003 (ol-ks_cancel-660-5) is 'approved' at the simulator, our row still PENDING (not yet applied) | chunks 16, calls 143,757, decisions 27, proposals {'APPLIED': 2, 'PENDING': 3}, credit calls in flight 0 |
| 5 (d) | approval APPROVED/APPLYING (approved, not yet applied) | D0 12:15 | approval apr_00003 (ol-ks_cancel-660-5) is 'approved' at the simulator, our row still PENDING (not yet applied) | chunks 16, calls 143,757, decisions 29, proposals {'APPLIED': 2, 'PENDING': 3}, credit calls in flight 0 |
| 6 (b) | mid-day while dialling | D1 11:00 | mid-day while dialling (D1 11:00) | chunks 59, calls 152,807, decisions 57, proposals {'APPLIED': 7, 'REJECTED': 1}, credit calls in flight 0 |
| 7 (e) | around the D3 11:30 supervisor prompt incident (validation in flight) | D3 11:45 | credit-spending call in flight: ledger row 1 'probe supervisor prompt change v8' state=sent | chunks 161, calls 174,507, decisions 91, proposals {'APPLIED': 11, 'REJECTED': 1}, credit calls in flight 1 |
| 8 (f) | around the D5 15:00 supervisor edit | D5 15:00 | around the D5 15:00 supervisor edit (D5 15:00) | chunks 271, calls 198,007, decisions 141, proposals {'APPLIED': 15, 'PENDING': 1, 'REJECTED': 1}, credit calls in flight 1 |
| 9 (g) | uncertain governance write in flight (SUBMITTING/APPLYING/AUTO_APPLYING) | D6 10:00 | write in flight: ol-nw_renewal-9240-18 SUBMITTING | chunks 301, calls 204,132, decisions 151, proposals {'APPLIED': 16, 'REJECTED': 1, 'SUBMITTING': 1}, credit calls in flight 1 |

Launch 10 ran to completion and exited 0.

## 3. Restart reconciliation (from the `decisions` table)

```
D0 00:00  controller_start     started at D0 00:00; ingested 187274 events in 5.2s
D0 10:00  controller_restart   restarted at D0 10:00; ingested 0 events in 0.0s
D0 12:15  controller_restart   restarted at D0 12:15; ingested 226 events in 0.0s
D0 12:15  controller_restart   restarted at D0 12:15; ingested 0 events in 0.0s
D0 12:15  controller_restart   restarted at D0 12:15; ingested 0 events in 0.0s
D1 11:00  controller_restart   restarted at D1 11:00; ingested 225 events in 0.1s
D3 11:45  controller_restart   restarted at D3 11:45; ingested 0 events in 0.0s
D5 15:00  controller_restart   restarted at D5 15:00; ingested 226 events in 0.0s
D6 10:00  controller_restart   restarted at D6 10:00; ingested 0 events in 0.0s
D6 10:00  recovery_reconcile   reconciled ol-nw_renewal-9240-18: SUBMITTING -> PENDING
D10 00:00  controller_finish    scenario finished at D10 00:00
```

## 4. Verification results (`scripts/verify_recovery.py`)

| # | check | result | evidence |
|---|---|---|---|
| 1 | None | PASS | no duplicates |
| 2 | None | PASS | 13 applied approvals, each exactly one config version; sim_log approval_applied=13, auto_applied=7 |
| 3 | None | PASS | 20 APPLIED rows vs 20 controller versions |
| 4 | None | PASS | 15 approvals {'applied': 13, 'rejected': 2}; lost=[]; inconsistent=[] |
| 5 | None | PASS | ghost=[]; submit_failed_but_landed=[] |
| 6 | None | PASS | none |
| 7 | None | INFO | {'APPLIED': 20, 'REJECTED': 2} |
| 8 | None | PASS | ours 492 chunks (0..491), simulator 492; dup=[]; per-chunk mismatches=[] |
| 9 | None | PASS | 324341 vs 324341 |
| 10 | None | PASS | calls rows 245032 (distinct event_id 245032) vs call events 245032 in 324341 event lines |
| 11 | None | PASS | 201 decisions, ids 1..201, wall regressions=0 |
| 12 | None | PASS | [{'launch': 1, 'expected': '(killed during start-up)', 'got': [], 'recovery_reconcile': []}, {'launch': 2, 'expected': 'controller_start', 'got': ['controller_start'], 'recovery_reconcile': []}, {'launch': 3, 'expected': |
| 13 | None | PASS | 1 |
| 14 | None | PASS | 3 bootstrap decisions for 3 workflows |
| 15 | None | PASS | 9 experiments, 9 experiment_designed decisions; overlapping actives [] |
| 16 | None | PASS | 7 experiments were active at some kill, all still present; 7 experiments have decisions in more than one controller launch: {'exp-0-welcome_message-0': [2, 6, 7, 8], 'exp-0-voice-0': [2, 6, 7, 8, 9], 'exp-1-welcome_messa |
| 17 | None | PASS | 1 incidents [('inc-ks_cancel-5040', 'closed')]; incident_opened decisions=1 |
| 18 | None | PASS | simulator credits used 9.0 (start 200.0, remaining 191.0); our ledger cost by state {'done': 6.0, 'sent': 3.0} |
| 19 | None | PASS | finished=True at minute 14400; final exit code 0 |
| 20 | None | PASS | rc=0 -> reports/crash_public_02_grade.md |

## 5. Outcomes with 9 kills vs the uninterrupted run

With kills (`reports/crash_public_02_grade.md`):

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.373 | +50.6% | 0.253 | +37.6% | 0.502 | +5.4% | 38% | 69 (330) |
| nw_kyc | 0.449 | +19.7% | 0.281 | +16.1% | 0.602 | +1.7% | -4% | 39 (31) |
| nw_renewal | 0.483 | +13.1% | 0.291 | +11.0% | 0.553 | +1.0% | 17% | 66 (55) |
| ALL | 0.425 | +27.3% | 0.271 | +22.2% | 0.541 | +2.1% | 26% | 174 (416) |

Uninterrupted, same commit (`reports/public_02_incidents.md`):

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.372 | +50.4% | 0.257 | +39.5% | 0.497 | +4.2% | 38% | 69 (330) |
| nw_kyc | 0.426 | +13.6% | 0.275 | +13.8% | 0.585 | -1.2% | 1% | 34 (31) |
| nw_renewal | 0.487 | +14.2% | 0.294 | +12.2% | 0.553 | +0.9% | 13% | 58 (55) |
| ALL | 0.422 | +26.3% | 0.273 | +23.0% | 0.535 | +0.9% | 26% | 161 (416) |

The two runs are not bit-identical and are not expected to be: a restart changes *when* in wall-clock terms each decision is taken relative to the simulator's random stream (every config change alters which random numbers later dials consume). What must hold — and does — is the governance and data invariants in §4, and outcomes of the same size. An earlier run (before commit `43dcd70`'s caller-ID fix) showed a much lower ks_cancel lift under kills; investigating it found a real decision flaw (§6.3), not a recovery flaw.

## 6. Bugs the harness exposed, and the fixes

### 6.1 Paid validation result lost between ledger and incident (fixed, committed in 15ac26c)

* **Evidence (first harness run, earlier session; console output and DB, not kept as a file).** Kill e landed
  after `credits_ledger` row 2 (`candidate fix for inc-ks_cancel-5025 (known_good)`, P1 pass 0.99) had
  committed as `done`, but before `_find_fix` wrote that result into the incident. After the restart, row 3
  validated P1 **again**: 3 credits spent twice (9 used vs 6 uninterrupted).
* **Cause.** `_find_fix` kept `tried[...]` and the chosen fix in memory, and committed them in a later,
  separate transaction from the ledger row.
* **Fix.** `src/outcomeloop/controller.py`:
  * `_validate(..., persist=None)` (line 603) runs `persist(run)` inside the transaction that marks the ledger
    row `done` (line 625).
  * `_find_fix` uses it through `keep()` (lines 662–680), so the result, `tried` and the fix selection commit
    together.
  * LLM suggestions are now stored on the incident in the same transaction as their ledger row (line 652).

### 6.2 Supervisor-prompt probe forgotten on a crash during the validation call (fixed, committed in d3e6bb2)

* **Evidence (first run of this session, all checks otherwise PASS; console output and DB, superseded by the
  canonical run).**
  * Kill e landed while ledger row 1 `probe supervisor prompt change v8` was `sent`.
  * `detect_halluc` had already cleared `prompt_probe:2` before calling `/validation/runs`. The restarted
    controller never probed P2, and the simulator had still charged the 3 credits.
  * The unsafe prompt was only caught at minute **5160** (D3 14:00) by the slower QA-flag detector, not at
    5025–5040.
  * ks_cancel hallucinated calls in that run: **98**, vs 73 uninterrupted.
  * In plain terms, the controller forgot a pending safety action after a crash.
* **Cause.** `src/outcomeloop/controller.py`, `detect_halluc`. The old code did
  `with db.tx(): db.kv_set(f"prompt_probe:{wf}", [])` **before** `self._validate(...)`, which made the probe
  at-most-once across crashes.
* **Fix** (lines 466–486). The probe is cleared inside `_validate`'s persist hook (`on_probe`, line 472), in
  the same transaction as the paid result and the incident it may open. If no validation happens (prompt moved
  on, no credits, call failed), the probe is still dropped as before (line 482). Trade-off: the probe becomes
  at-least-once. A kill during the call re-runs it at a cost of 3 credits, which is better than leaving a bad
  customer-facing prompt unchecked.
* **Verified.**
  * Canonical run: kill e again landed on ledger row 1 `sent`. The probe survived in `kv`, re-ran at 5040 and
    opened the incident in that same minute.
  * Supplementary run: same result.
  * `pytest`: 137 passed, 1 skipped.

### 6.3 Caller-ID: volume fatigue mistaken for a spam flag (found by comparing crash and clean runs; fixed)

* **Evidence.** In a crash run at commit c16cdaa, after the flagged D2 was removed, D1 (carrying traffic for the whole history)
  looked "degraded" next to the fresh D3 (ratio < 0.85) and was ramped out, leaving 100 % of ks_cancel traffic on D3, which then
  fatigued; ks_cancel conclusion-rate lift fell to +28 % vs +53 % uninterrupted. The uninterrupted run had escaped by chance.
* **Cause.** The relative test (a number vs the other numbers in the same window) cannot distinguish a sudden flag from steady
  volume fatigue next to a fresh number.
* **Fix** (`detectors.did_health`). A number in rotation with a week of its own history is degraded only if it *also* dropped
  > 15 % against its own previous week (z < −3). Numbers on probe keep the relative-only test.
* **Verified.** Final crash run above: ks_cancel +50.6 % under 9 kills vs +50.4 % uninterrupted; flagged number at 0 % share
  from D3 in both.

## 7. What a crash loses

All durable state is committed before any side effect that depends on it. That covers proposal rows before
`POST`, chunk rows with their checkpoint in one transaction, inbox events before handlers, and paid results
together with their consumers. So no *durable* state is lost. What is lost:

* **The in-flight HTTP response.**
  * For governance writes (submit, apply, auto-apply) this is harmless: they carry idempotency keys
    (`proposal_id`, `approval_id`) and are reconciled against `/approvals` and `/config/history` before any
    retry (kill g, and APPLYING in the supplementary run).
  * For `/sim/advance` it is harmless too: the restart re-reads `/sim/state` and ingests whatever that tick
    produced (the "225/226 events" restarts).
* **Credit-spending calls without an idempotency key** (`/validation/runs`, `/llm/suggest-fixes`). If the kill
  lands while the request is on the wire, the simulator may charge and we never see the result. The ledger row
  stays `sent` (row 1 in this run, 3 credits). Since fix 6.2 the dependent action is retried, which costs up to
  one extra call. The ledger makes that spend visible: check 18 accounts for it.
* **In-memory scheduling hints.**
  * `Controller.urgent` (line 114) asks for a decision at the next tick instead of waiting for the hourly
    cadence, and is set for example on a supervisor prompt edit (line 295). It is not persisted, so after a
    restart the decision waits until the next hourly tick: up to 45 sim minutes, 15 in this run.
  * In-process caches (feature arrays, code maps) are rebuilt from SQLite on start.
* **Small audit or bookkeeping gaps in microsecond windows with no I/O between commits** (not observed in any
  run):
  * the `proposal_submitted` decision is written in a transaction after the proposal row's PENDING update;
  * the auto-apply ramp budget (`ramp:{wf}:{day}`) is updated after the APPLIED commit.
  A kill in exactly that gap would drop one audit line or under-count one ramp step. It cannot cause a double
  apply.

## 8. Reproduce

```bash
export PYTHONUTF8=1
scripts/crash_recovery.sh                    # simulator on :8711; ~75 s wall; exits non-zero if any check fails
# options: --port 8712  --skip-grade  --timeout-s 1800  (see scripts/crash_recovery.py --help)
# re-run only the checks against a still-running simulator:
python scripts/verify_recovery.py --url http://127.0.0.1:8711 --db state/crash_public_02.db \
    --run-dir runs/crash_public_02 --baseline runs/base_public_02_incidents \
    --timeline reports/crash_recovery_timeline.json
```

Outputs:

* `reports/crash_recovery_timeline.json` (timeline plus verification results)
* `reports/crash_public_02_grade.md`
* `runs/crash_public_02/` (simulator run dir)
* `runs/crash_public_02_ctl.log` (all 10 controller launches, separated by `===== launch N =====` markers)
* `runs/crash_public_02_sim.log`
* `state/crash_public_02.db`

Inspect a restart from the audit store:

```bash
PYTHONPATH=src OUTCOMELOOP_DB=state/crash_public_02.db python -m outcomeloop audit --kind controller_restart
PYTHONPATH=src OUTCOMELOOP_DB=state/crash_public_02.db python -m outcomeloop audit --kind recovery_reconcile
```

Kill timing reacts to state, not to wall-clock offsets, so the same kill labels land on the same kinds of
states on any machine. Exact sim minutes for the state-driven kills (c, d, e, g) can vary between runs, because
they depend on when the controller reaches the targeted state.
