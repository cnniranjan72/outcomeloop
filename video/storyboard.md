# OutcomeLoop walkthrough video: storyboard (5:00 maximum)

No video has been recorded yet. This is the plan. The narration is in `video/voiceover_script.md` and the
captions are in `video/subtitles.srt`.

Every long-running step is computed before recording (see "Pre-recording setup" in the voice-over script). On
screen we only run read-side commands against finished stores, open files, and show short pre-recorded log
excerpts. Commands assume the repository root with `export PYTHONPATH=src PYTHONUTF8=1`.

| # | Time | Duration | Scene |
|---|---|---|---|
| 1 | 00:00–00:25 | 25 s | Intro |
| 2 | 00:25–01:05 | 40 s | Architecture |
| 3 | 01:05–02:00 | 55 s | Working execution |
| 4 | 02:00–03:00 | 60 s | Governance and experimentation |
| 5 | 03:00–03:45 | 45 s | Recovery and auditability |
| 6 | 03:45–04:30 | 45 s | Results |
| 7 | 04:30–05:00 | 30 s | Conclusion |

---

## Scene 1: Intro (00:00–00:25, 25 s)

| Time | On screen | Action |
|---|---|---|
| 00:00–00:10 | `README.md` rendered (VS Code Markdown preview or GitHub). Title and the first paragraph. | Open `README.md`, preview mode, scrolled to the top. |
| 00:10–00:25 | README › "Core features (C1–C15)" table. | Scroll slowly to the table. Hover over the Built / Partial / Cut column. |

## Scene 2: Architecture (00:25–01:05, 40 s)

| Time | On screen | Action |
|---|---|---|
| 00:25–00:45 | README › Diagram A (system architecture, rendered Mermaid). | Scroll to "Architecture". Zoom so the simulator and controller subgraphs fill the frame. |
| 00:45–01:05 | README › Diagram B (control loop). Then a 3-second cut to `src/outcomeloop/` in the file tree. | Scroll to "Autonomous decision lifecycle". Then click the `src/outcomeloop` folder in the explorer. |

## Scene 3: Working execution (01:05–02:00, 55 s)

| Time | On screen | Action |
|---|---|---|
| 01:05–01:25 | Terminal: start of a run. | Run `scripts/run_scenario.sh public_01_dev 8700` live for about 15 s. Show the "starting simulator" line, then `tail -f runs/ctl_public_01_dev.log` until the first `D0 done` line. Cut away; do not wait for the end. |
| 01:25–01:45 | Terminal: loop health of a finished run. | `python -m outcomeloop --db state/public_02_incidents.db status` |
| 01:45–02:00 | Terminal: what the controller did on one workflow. | `python -m outcomeloop --db state/public_02_incidents.db audit --wf ks_cancel --limit 200 \| grep -v " hold " \| head -20` |

## Scene 4: Governance and experimentation (02:00–03:00, 60 s)

| Time | On screen | Action |
|---|---|---|
| 02:00–02:20 | README › Diagram E (approval sequence). | Scroll to "Governance and approval lifecycle". |
| 02:20–02:35 | Terminal: why the controller waited. | `python -m outcomeloop --db state/public_02_incidents.db audit --kind hold --limit 8` |
| 02:35–03:00 | Terminal: one-screen supervisor view with experiments and lifts. | `python -m outcomeloop --db state/public_02_incidents.db supervisor ks_cancel`. Highlight the "Being tested / winning" lines. |

## Scene 5: Recovery and auditability (03:00–03:45, 45 s)

| Time | On screen | Action |
|---|---|---|
| 03:00–03:15 | README › Diagram F (crash recovery), then `reports/crash_recovery_timeline.json` with the verification section. | Scroll to "Idempotency and crash recovery", then open the JSON and fold it to the `verification` key. |
| 03:15–03:45 | Terminal: the review question answered from our store. | `python -m outcomeloop --db state/public_02_incidents.db why ks_cancel --at "D3 13:30"`. Highlight "Approved by", "Diff" and the "What happened next" lines. |

## Scene 6: Results (03:45–04:30, 45 s)

| Time | On screen | Action |
|---|---|---|
| 03:45–04:05 | `reports/public_01_dev.md` and `reports/public_02_incidents.md`, outcome tables. | Open each report in Markdown preview. Keep the "Outcomes vs baseline" table in frame. |
| 04:05–04:20 | `reports/public_02_incidents.md` › Incidents and "Decaying variants". | Scroll down. |
| 04:20–04:30 | `reports/public_03.md`, throughput table. | Open the load report. Show the throughput rows. |

## Scene 7: Conclusion (04:30–05:00, 30 s)

| Time | On screen | Action |
|---|---|---|
| 04:30–04:50 | README › "Limitations and trade-offs". | Scroll to the section. |
| 04:50–05:00 | README › "Setup" and "Running each scenario" code blocks, then the repo name. | Scroll, hold, fade out. |
