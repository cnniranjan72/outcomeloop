How to read it, and what it taught us:

* **False winners.** `r3_null_effects` has no true welcome/voice effects, so every variant change it applies is
  acting on noise. Across both seeds the grader marks **0 harmful** changes: the tests found nothing to promote
  because there was nothing to find. Its lift comes from caller-ID load spreading and call-hour weights, which do
  not depend on variant effects. This is the out-of-sample check of the α-spending / Holm design.
* **Generalisation.** Every scenario improves the conclusion rate at both seeds, including truths we never tuned
  on (`r1`), policies with no auto-apply and short TTLs (`r2`), and odd shapes (`r6`). Seed replicas agree to
  within a few points, so the gains are not luck.
* **What the suite broke, and what we changed** (all fixed before the table above was produced):
  - a flagged caller ID kept ~91 % of traffic for days on an approval-only workflow (the "unknown never moves
    traffic" rule also protected a *measured-degraded* number) → a degraded number always gives up its share;
    emergencies only need the best-case approver latency;
  - decay was never tested on a small `next_campaign_only` workflow (15 % holdout ≈ 100 calls/day; versions reset
    at promotion) → adaptive 24–72 h window, earlier campaigns' concurrent calls kept;
  - with 12 credits the second prompt incident was never fixed → validation size adapts to the balance;
  - a genuine winner rolled back by a 5 % test repeated hourly → both decay clauses at 1 %;
  - 20 h MTTR on a borderline-unsafe prompt (validation exactly at the threshold) → pooled second run, and the
    benefit of the doubt goes to safety once production flags have fired;
  - a promotion applied 30 h after it was decided, after the effect had faded → re-checked while pending.
* **What remains, honestly.** Two recurring "harmful" verdicts: (a) the first exploration launch on workflows
  whose challengers are worse in truth (the price of a 40 % exploration share; 1–2 % expected engagement), and
  (b) reverting the "persuasive" prompt, which the grader counts both as an incident fix and an engagement loss —
  a safety choice we would make again. On approval-only `next_campaign_only` workflows a flagged caller ID still
  takes ~3 days to leave all traffic, because running campaigns keep their locked allocation.
* **The trade we made.** These fixes cost about 2–3 points of conclusion-rate lift on public_01 compared with
  the version tuned only on the public scenarios. We kept them: they remove failure modes that hidden scenarios,
  which "differ in truth, incidents and policy", are designed to find.
