# OutcomeLoop walkthrough video: voice-over script

This is the narration for `video/storyboard.md`. It is written at about 140 words per minute, in the first
person plural, and no video exists yet.

Before recording, replace each `{{…}}` placeholder with the value from the named report file. Read numbers
exactly as they appear in `reports/`.

## Recording instructions

**Screen and terminal**

- Record at 1920×1080. Use one window for the editor (VS Code with Markdown preview and a Mermaid-capable
  preview) and one terminal.
- Terminal: Windows Terminal or any Linux terminal, 120 columns × 32 rows, monospace font at 18 pt, dark theme,
  prompt shortened to `$ `.
- Editor: zoom to 150 %, sidebar hidden except in Scene 2. Turn off notifications.
- Set the UTF-8 environment in the recording terminal (`export PYTHONUTF8=1`), so `—` and `→` render correctly.

**Pre-recording setup.** Run this the day before. Each scenario takes minutes and the load test takes much
longer, so never run these on camera.

```bash
cd outcomeloop
python3 -m venv .venv && . .venv/bin/activate      # Windows Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt
export PYTHONUTF8=1 PYTHONPATH=src
scripts/run_scenario.sh public_01_dev 8700         # -> state/public_01_dev.db, reports/public_01_dev.md
scripts/run_scenario.sh public_02_incidents 8701   # -> state/public_02_incidents.db, reports/public_02_incidents.md
scripts/load_test.sh 8703                          # -> reports/public_03.md
scripts/crash_recovery.sh                          # -> reports/crash_recovery_timeline.json
python -m pytest -q                                # note the pass count for Scene 6
# dry-run every on-screen command once, so outputs are cached in your head and paths are right:
python -m outcomeloop --db state/public_02_incidents.db status
python -m outcomeloop --db state/public_02_incidents.db audit --kind hold --limit 8
python -m outcomeloop --db state/public_02_incidents.db supervisor ks_cancel
python -m outcomeloop --db state/public_02_incidents.db why ks_cancel --at "D3 13:30"
```

Re-running `run_scenario.sh public_01_dev` in Scene 3 deletes and rebuilds `state/public_01_dev.db`. Either
record Scene 3 with a different port and DB name, or re-run the scenario after recording. Check the time of the
prompt incident in the new store with `audit --wf ks_cancel --kind incident_opened`. If ids or times changed,
adjust the `--at` argument and the narration in Scenes 3 and 5.

**How to record and cut**

- Record each scene as its own clip. Record the narration separately to the scene's duration, then lay the
  clips under it.
- Scene 3: record the live start for about 20 s and cut to the finished-store commands. Do not show waiting.
- Cut on command completion. Never show typing longer than about 2 s: paste commands or speed up typing 4×.
- Keep total length at or under 5:00. If you run long, trim Scene 4's `hold` listing first.
- Burn in `video/subtitles.srt`, or ship it as a sidecar file.

---

## Scene 1: Intro (00:00–00:25, about 58 words)

> This is OutcomeLoop, an autonomous, governed controller for Formi's outbound voice agents. For every
> workflow it watches pickup and engagement, tests better welcome messages and voices, asks the client for
> approval, applies what is approved, and backs out of what stops working. We built eleven of the fifteen
> capabilities fully, three partly, and cut one. That one is fair sharing of credits across tenants.

## Scene 2: Architecture (00:25–01:05, about 92 words)

> The design is deliberately small. There is one Python process and one SQLite file. The only dependencies
> are httpx and numpy. The simulator only moves when we advance it, so the loop is synchronous and
> deterministic.
>
> Every fifteen simulated minutes we poll approvals and apply what was approved. On the hour, we run a
> decision for each workflow: caller-ID health, hallucination checks, experiment steps, then a desired
> configuration. We compare that with the live configuration and route the difference through governance.
> Then we advance the clock and ingest the new events, each chunk in one transaction.

## Scene 3: Working execution (01:05–02:00, about 128 words)

> Here is a real run starting. The script creates a baseline, starts the simulator, and runs our controller
> through run dot s h, the same entry point the graders use. It logs one line per simulated day.
>
> Now a finished run of the incidents scenario. The status command reads only our database. It shows events
> ingested, ingest throughput, credits remaining, and the recent alerts. There is one hallucination incident
> and one decay rollback, and nothing is stuck in an uncertain state.
>
> The audit trail for the Kestrel workflow shows what happened. On day three at eleven thirty a supervisor
> shipped prompt P2. Fifteen minutes later our validation probe failed it. A known-good prompt from our own
> history passed, and we sent a single, prompt-only approval request. It was applied at one thirty and
> verified that evening.

## Scene 4: Governance and experimentation (02:00–03:00, about 138 words)

> Nothing changes on a client's agent without passing the governance boundary. We write the request to
> SQLite before sending it. We keep one open request per workflow and batch everything else into it. We only
> send when the slowest possible approver reply still lands before expiry.
>
> These hold records are the controller choosing to wait. It waits outside approver hours, when the reply
> could arrive after expiry, at the fatigue limit, where one slot is always kept for incidents, and after a
> rejection. Caller-ID changes are auto-applied where policy allows, in steps no larger than max shift. We
> never auto-apply anything a customer hears.
>
> Experiments are factorial: sixty percent incumbent, forty percent challengers. An O'Brien-Fleming alpha
> budget and Holm's correction keep the false-winner rate at five percent. Here, V3 won by about twelve
> percent, after guardrail, cohort and stability checks.

## Scene 5: Recovery and auditability (03:00–03:45, about 104 words)

> Crash safety comes from three rules. Each event chunk is ingested in one transaction with its checkpoint.
> Each remote write is recorded as an intent before we send it. And on restart we reconcile every uncertain
> write against the simulator before doing anything else. Our harness hard-kills the controller seven times
> and verifies that nothing was applied twice and no approval was lost.
>
> And this is the review question, answered from our own store. Why did Kestrel's workflow change at one
> thirty on day three? Who approved it? What happened next? Here are the approval id, the exact diff, the
> validation evidence, and the verification that followed.

## Scene 6: Results (03:45–04:30, about 100 words)

> These are the grader's reports against a no-op baseline. On the development scenario the conclusion rate
> rose 13.3% against the baseline. On the incidents scenario it rose 26.8%. The unsafe
> prompt was fixed in 60 minutes, and the spam-flagged caller ID dropped to zero share. The grader also
> marks a few experiment launches as harmful. Exploring costs something, and we report it rather than hide
> it.
>
> On the load scenario we ingest about 57,000 events per second and spend 69 to 91
> seconds of controller time per simulated day, at 491 megabytes peak memory. The test suite has 162 tests, all passing.

## Scene 7: Conclusion (04:30–05:00, about 68 words)

> We are explicit about the limits. Experiments always optimise engagement and guard pickup. There is no
> welcome-by-voice interaction check. And a single SQLite writer is the first thing to change at ten times
> scale, by moving to Postgres partitions and sharding workers by workflow. Everything you saw runs from the
> README with one script per scenario. Thank you.
