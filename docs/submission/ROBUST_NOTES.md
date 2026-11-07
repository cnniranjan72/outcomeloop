How to read it, and what it taught us:

* **False winners — measured, not inferred.** `r3_null_effects` has no true welcome/voice effects, so every
  experiment winner there is a false winner. The grader's "0 harmful" on it is weak evidence (a null variant change
  is neutral by construction), so the table counts winners from our own audit store: **2 winners in 16 null
  experiments** across the two seeds. The design bounds the false-winner rate at ≤ 5 % per experiment (Holm ×
  explicit O'Brien-Fleming budget; every experiment's spent α ≤ 0.05 in the store); 16 experiments give an expected
  ≤ 0.8 false winners, and observing ≥ 2 has probability ≈ 0.19 at exactly 5 % — consistent with the bound, not
  proof of it. Both were near the boundary (pooled z = 3.04 against a Holm threshold of p 0.0054; a cohort-level
  z = 3.35). The pooled one was later **rolled back by the holdout decay test** — the second line of defence
  working as intended. Before our audit fix, the cohort-level family re-spent the look's α (a real 2α bug); it now
  gets 20 % of it.
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
