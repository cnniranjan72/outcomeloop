# Outcome-First Agent Loop — Submission (OutcomeLoop)

**Name:** {{NAME}} · **Date:** {{DATE}} · **Hours actually spent :** {{HOURS}} ·
**Language / storage:** Python 3.12 (stdlib + `httpx`, `numpy`) / SQLite (WAL, embedded file — no service)

> Repository map: controller in `src/outcomeloop/`, entry point `./run.sh <SIM_URL>`, grade reports and load /
> crash evidence in `reports/`, design detail in `docs/DESIGN_DECISIONS.md`, runbook in `docs/OPERATIONS.md`.

---

## 0. TL;DR

- OutcomeLoop is a single-process controller that ingests every event exactly once into SQLite, keeps one
  shared cohort object per workflow, detects caller-ID and hallucination incidents on populations, runs
  factorial welcome × voice experiments with a sequential test that controls the false-winner rate, and routes
  every change through governance with one batched proposal per workflow.
- **public_01:** conclusion rate {{P01_ALL}} vs the no-op baseline (primary KPI: {{P01_PRIMARY}}), {{P01_HARM}}.
- **public_02:** conclusion rate {{P02_ALL}}; spam-flagged caller ID moved off within ~2 h by policy-permitted
  auto-apply; supervisor's unsafe prompt reverted through an approval with validation evidence (MTTR
  {{P02_MTTR}} min); {{P02_HARM}}.
- Kill -9 at any point and it resumes ({{CRASH_SUMMARY}}); public_03 load: {{LOAD_SUMMARY}}.
- Out of sample: six scenarios of our own (different truth, policies, incidents, incl. one with **no true effects**)
  × 2 seeds plus both public scenarios — {{ROBUST_HEADLINE}}.
- Deliberately not built: LLM-driven anything beyond fix suggestions, fair-share across
  tenants (C15), a UI (the supervisor view is a CLI over the same store).

## 1. Assumptions

{{ASSUMPTIONS}}

## 2. Scope decisions

| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Event ingestion at load scale | **Built** | Everything else is only as good as ingestion; exactly-once is the basis of crash safety. One transaction per chunk (rows + checkpoint), `INSERT OR IGNORE` on the event key. | Rollup tables at ingest so decisions don't scan raw rows at 10×. |
| C2 | Lead/feature joins, one shared cohort object | **Built** | Product's hard requirement; features are joined onto every call row at ingest, cohort membership has one SQL implementation used by detection, experiments and the supervisor view, and it is mirrored 1:1 into `config.cohorts`. | Slice-based refinement of the cohort set (e.g. add `lang=ta`) via proposal. |
| C3 | Bootstrapping from history | **Built** | History is the only evidence on D0: hour-of-day profiles, per-number pickup, QA flag baseline, cohort choice (likelihood-ratio test). | — |
| C4 | Call-time optimisation | **Built** (cohort weights; per-person as a randomised experiment) | Cohort-level hour weights from smoothed history, dry-run estimated. Per-person preferred hours run as a self-terminating randomised experiment (treatment vs control people, pickup per dial), only where `schedule` is auto-appliable; it is kept only on evidence. | Extend per-person evidence to people returning from older campaigns. |
| C5 | Caller-ID health | **Built** | Clearest outcome lever on pickup and a named incident type; randomisation makes it measurable. Fast/slow windows, equal split over healthy numbers, rest + re-probe, ramped auto-apply. | Load-aware model (pickup vs per-number volume) for planned rotation. |
| C6 | Variant experimentation | **Built** | The core of "earning autonomy": factorial design, planned n, O'Brien-Fleming α spending, Holm, guardrail, cohort harm check. | Interaction check before promoting a combination. |
| C7 | Winner promotion, decay, rollback | **Built** | Holdout-based decay test against the promotion's lower confidence bound; rollback via approval; blacklist. | Faster decay detection with a CUSUM on the holdout lift. |
| C8 | Hallucination incident response | **Built** | Safety in a regulated business; validation probe on supervisor edits, two-signal confirmation, known-good first then LLM, engagement-verified fix. | Prompt A/B is impossible (one prompt per workflow); a staged before/after design would be next. |
| C9 | Governance client | **Built** | The non-negotiable boundary: state machine, batching, approver-hours timing with worst-case latency, fatigue with incident reserve, expiry = re-plan, stale = re-plan, auto-apply within policy and ramps. | Approver-attention budget shared across a tenant's workflows. |
| C10 | Impact scores, affected leads, dry runs | **Built** (honest, simple) | Every proposal carries all four with their basis; dry runs replay our own calls and state their bias. | Calibrate impact score against realised lift. |
| C11 | Supervisor view | **Built** (CLI + read-only HTTP) | `python -m outcomeloop supervisor <wf>` and `serve-views` (`/supervisor/<wf>`): tested / winning / waiting for you / changed today / incidents, from the same store as everything else. | A weekly summary for Compliance generated from the decision log. |
| C12 | Queryable audit store | **Built** | `decisions` is append-only (DB triggers); `why <wf> --at <t>` and `customer <person>` answer the review's question from our store. | — |
| C13 | Crash recovery, demonstrated | **Built** | SRE's non-negotiable; `scripts/crash_recovery.sh` kills with SIGKILL/TerminateProcess at several points and verifies. | — |
| C14 | Observability of the loop | **Partial** | `metrics` table (ingest events/s, lag, per-tick decide/advance time, credits, open proposals, memory), `status`, and `alerts`, which evaluates the paging rules of §10 from the store and exits non-zero when one fires (cron/pager-ready). | Export to the platform's metrics stack; wire `alerts` to the pager. |
| C15 | Fair credits / attention across tenants | **Cut** | Public scenarios use ~0–10 % of credits; fatigue is per workflow already. Building fair-share without contention data would be guesswork. | Per-tenant credit and request budgets with priority by impact score. |

**Principle.** Build whatever the hidden-scenario score and the governance boundary can't do without (ingestion,
governance, statistical experimentation, the two incident types, crash safety, audit) properly and with tests;
make the rest honest and minimal; cut what needs data we don't have. Every "Partial" is a usable slice, not a
stub.
