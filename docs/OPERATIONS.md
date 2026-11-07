# OutcomeLoop on-call runbook

This runbook is for the engineer who owns OutcomeLoop while its author is away. Every command here is a real
command. Run them from the repository root with `export PYTHONPATH=src PYTHONUTF8=1`. `--db` must come
**before** the subcommand.

## 1. Start and stop

**Start**

```bash
OUTCOMELOOP_DB=state/<name>.db ./run.sh http://<sim-host>:<port>
```

- `run.sh` picks the interpreter: `OUTCOMELOOP_PYTHON`, then `.venv`, then `python3`.
- It installs `requirements.txt` if `httpx` or `numpy` is missing.
- It runs the controller in a restart loop. An abnormal exit is restarted after 5 s against the same DB, up to
  `OUTCOMELOOP_MAX_RESTARTS` (default 20) times.
- It exits 0 only when the scenario has finished.

To run a whole scenario including the simulator and grading, use `scripts/run_scenario.sh <scenario> [port]`.
Note that this deletes `state/<scenario>.db` first.

**Stop.** Kill the process at any time. There is no shutdown procedure, and none is needed: every state change
is a committed transaction, and remote writes are reconciled on the next start (section 5). Kill the `run.sh`
loop as well as the Python child, or `run.sh` will restart the child.

**Resume.** Run the same `run.sh` command with the same `OUTCOMELOOP_DB`, against the same simulator process.

## 2. Where state lives

| What | Where |
|---|---|
| All durable state: events, cohorts, experiments, proposals, incidents, credits, audit, metrics | `$OUTCOMELOOP_DB` (default `state/outcomeloop.db`) plus its `-wal` / `-shm` files |
| Archived state from a different simulator world | `state/<name>.<epoch>.old` (+ `-wal`, `-shm`) |
| Controller log | stdout of `run.sh` (`runs/ctl_<name>.log` when started by `run_scenario.sh`) |
| Tenant preferences (Kestrel 11:00 start, 2 requests/day) | `config/tenant_preferences.json`, or `$OUTCOMELOOP_TENANT_PREFS` |
| Thresholds | `src/outcomeloop/config.py` (`Settings`). Change them in code and commit. There is no runtime override. |

Nothing that affects a decision is held only in memory. The in-memory caches (feature arrays, code dictionary)
are rebuilt from the DB on start.

## 3. Inspect

```bash
DB=state/<name>.db
python -m outcomeloop --db $DB status                          # loop health, recent alerts, proposals by state
python -m outcomeloop --db $DB supervisor <workflow>           # one screen per workflow
python -m outcomeloop --db $DB audit --wf <workflow> --limit 50
python -m outcomeloop --db $DB audit --kind error --limit 20
python -m outcomeloop --db $DB why <workflow> --at "D3 14:00"  # why did it change, who approved, what next
python -m outcomeloop --db $DB customer <workflow>:p0004567 --day 3
python -m outcomeloop --db $DB decision <id>                   # one decision: why, evidence, linked proposal/incident, before/after
```

The read commands open SQLite only, so they work while the controller or the simulator is down. WAL allows
reading during a run. Raw SQL is fine for anything else:

```bash
sqlite3 $DB "SELECT proposal_id, state, kind, approval_id, notes FROM proposals ORDER BY created_minute DESC LIMIT 10"
sqlite3 $DB "SELECT name, value, minute FROM metrics WHERE name='ingest_lag_minutes' ORDER BY id DESC LIMIT 8"
sqlite3 $DB "SELECT id, minute, kind, purpose, state, cost FROM credits_ledger"
sqlite3 $DB "SELECT evidence FROM decisions WHERE decision_id=<id>"     # full evidence JSON of one decision
```

Never UPDATE or DELETE `decisions`: triggers abort it. Do not edit other tables by hand while a controller is
running.

## 4. Alerts

OutcomeLoop writes alert-class rows to `decisions` and samples to `metrics`. It does not page anyone itself.
Wire these signals to the pager as follows.

### Page

| Alert | Trigger | What to look at | What to do |
|---|---|---|---|
| Controller down | No new `metrics` rows for more than 5 wall minutes during a run, or `run.sh` printed `giving up after N restarts` | Log tail, `audit --kind error`, `audit --kind controller_restart` | Fix the cause: usually the simulator is unreachable (section 7) or there is a code error. Then restart `run.sh` with the same DB. It resumes. |
| Ingest lag in window | `ingest_lag_minutes` > 30 while workflows are inside their dialling windows | `ingest_seconds` and `advance_seconds` metrics, simulator health | If ingest is slow, check disk and DB size. If the simulator is slow, it is not ours. Lag outside dialling windows is normal, because no chunks arrive. |
| Approved but not applied | Any `proposal_lapsed` decision, or a proposal in `APPROVED` for more than 1 tick | `proposals.notes` for that id, and `why <wf> --at <time>` | `notes` holds the apply error. `STALE` is correct behaviour after a supervisor edit, and the next plan re-proposes. Repeated apply errors with another code are a bug: capture the DB. |
| Credits near reserve | `credits_remaining` < 1.1 × 40 % of `kv credits_start` | `credits_ledger` | See section 6. |
| Repeated decide errors (`workflow_stuck`) | 3 or more `error` decisions for one workflow within 3 sim-hours (`alerts` reports it as `workflow_stuck`) | The `summary` holds the exception text | The other workflows keep running. Capture the DB copy and log, then fix and redeploy. Restarting is safe. |

### Do not page (review in business hours or let the supervisor view show it)

| Signal | Why it does not page |
|---|---|
| `incident_opened` (hallucination) | The controller validates candidates and proposes a fix itself. Escalate only if no `incident_fix_selected` follows within 2 h, which usually means credits ran out or nothing validated. |
| `did_health ... -> degraded` | Moved off automatically (auto-apply ramp) or proposed as an emergency. |
| `decay_detected` | A rollback proposal follows automatically. |
| `alert` (KPI drift, 12:00 daily) | Context for supervisors. There is no automatic action. |
| `hold` | Expected waiting: approver hours, worst-case expiry timing, fatigue, rejection cool-down. |
| `proposal_rejected` / `proposal_expired` | Approver judgement. The controller re-plans from fresh data. |
| `incident_not_confirmed` | The QA flag spike was not confirmed by validation, so nothing changed. This is the false-positive guard working. |

## 5. Restart and recovery procedure

1. Make sure no other controller is writing the same DB: `ps aux | grep outcomeloop`, or Task Manager on
   Windows. Two writers would serialise on SQLite locks, but both would act on the world.
2. Copy the DB before touching anything if the incident needs a post-mortem:
   `sqlite3 $DB ".backup state/postmortem.db"`.
3. Start `./run.sh <SIM_URL>` with the same `OUTCOMELOOP_DB`. On start the controller:
   - checks the world fingerprint, and archives the DB if this is a different world (section 7);
   - ingests the chunks it missed;
   - reconciles every `SUBMITTING`, `APPLYING` or `AUTO_APPLYING` proposal against `/approvals` and
     `/config/history`, writing one `recovery_reconcile` decision per row;
   - re-runs unhandled inbox events and re-reads each workflow's live config.
4. Verify:
   - `audit --kind controller_restart` shows the restart.
   - `audit --kind recovery_reconcile` shows how each in-flight write resolved.
   - `status` shows proposals by state with nothing left in an uncertain state.
5. To prove recovery end to end on a scratch simulator, run `scripts/crash_recovery.sh`. It kills the
   controller 7 times at chosen moments and runs `scripts/verify_recovery.py`. The result is in
   `reports/crash_recovery_timeline.json`.

What a crash can cost:

- A validation or LLM call that was sent but whose result was not committed. Its ledger row stays `sent`, and the
  same candidate may be validated again after restart (at most 3 credits).
- The wall-clock metrics of the interrupted simulated day.

## 6. Credits running low

1. `sqlite3 $DB "SELECT kind, purpose, state, SUM(cost) FROM credits_ledger GROUP BY 1,2,3"` shows what spent
   them.
2. Rules in force (`Controller._credits_ok`):
   - Non-incident work must leave 40 % of the starting budget untouched.
   - Incident work (validation probes, candidate validation, LLM suggestions) may spend down to 0.
   - Today all spending is incident work.
3. Each incident spends 3 credits per validation (n = 300). It validates up to 3 candidates per tick and calls
   the LLM (3 credits) at most once, only after known-good prompts are exhausted.
4. If credits are exhausted, `_validate` returns nothing and the incident logs `incident_no_fix`. The bad prompt
   stays live until a human acts. Tell the client supervisor through the `supervisor` view output. A prompt change
   still needs approval with validation evidence: do not bypass governance.
5. Rows stuck in `sent` are calls whose outcome we never recorded (a crash or an uncertain response). Treat them
   as spent.

## 7. The simulator world changed

Symptom: the log says `simulator world changed (A -> B); archiving ... to ...`.

- **Meaning.** Our DB belongs to a different world. Either the scenario name differs, the first history chunk
  differs, or our checkpoint is ahead of the simulator's clock. A restarted simulator is always a new world,
  because it keeps state in memory.
- **Action.** None needed for a deliberate new run. The old DB is at `state/<name>.<epoch>.old` and can still be
  read with every CLI command (`--db state/<name>.<epoch>.old`).
- **If it was not deliberate,** for example the simulator crashed and restarted mid-run: the run cannot be
  resumed, because the world it learned from is gone. Start the scenario again. Keep the `.old` file for the
  audit trail.

## 8. Backup

- **Hot backup while running:** `sqlite3 $DB ".backup state/backup-$(date +%Y%m%d-%H%M).db"`. This is
  consistent under WAL.
- **Cold backup:** stop the controller, then copy `$DB`, `$DB-wal` and `$DB-shm` together.
- **Restore:** stop the controller and copy the backup to `$OUTCOMELOOP_DB`. A restored DB that is **behind**
  the simulator resumes: it re-ingests the chunks after its checkpoint and reconciles proposals against the
  simulator. Any approval we submitted after the backup is reported in the startup notes as an orphan
  (`orphan approval ...`) and is not adopted. Check those with `GET /approvals` before acting.
- **Retention:** the DB holds per-call rows, which the `customer` query needs for "what did this person hear".
  Agree retention with Compliance before deleting.

## 9. Quick reference

| Question | Command |
|---|---|
| Is the loop healthy? | `status` |
| What is a workflow doing right now? | `supervisor <wf>` |
| Why did X change at T? | `why <wf> --at "D3 14:00"` |
| Why is nothing being sent? | `audit --wf <wf> --kind hold` |
| Explain one decision fully (evidence, links, before/after) | `decision <id>` (ids are the `#n` in `audit`; `--full` for all evidence) |
| One lifecycle (experiment, incident, decay) | `audit --wf <wf> --kind "experiment_*"` |
| What did a customer hear and why? | `customer <wf>:p<id> --day <n>` |
| What failed? | `audit --kind error` |
| What happened on restart? | `audit --kind recovery_reconcile` |
