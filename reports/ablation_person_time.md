# Ablation: per-person call time on vs off

Same code (commit `af58d38`/`515a038` era), same 16 runs (6 generated scenarios × 2 seeds + both public scenarios × 2 seeds,
Linux containers, 2 vCPU / 2 GB each); only `OUTCOMELOOP_PERSON_TIME` differs (`scripts/robustness.sh` with
`ROBUST_OUT`/`ROBUST_REPORT`). Numbers are the simulator grader's conclusion-rate change vs the no-op baseline.

| scenario | ON | OFF | ON − OFF (pp) | pickup ON / OFF | changes ON / OFF | harmful ON / OFF |
|---|---|---|---|---|---|---|
| public_01_dev | +12.0% | +12.6% | -0.5 | +8.6% / +8.3% | 26 / 17 | 2 / 1 |
| public_01_dev_s2 | +15.1% | +14.6% | +0.4 | +9.2% / +9.1% | 23 / 16 | 0 / 0 |
| public_02_incidents | +24.4% | +25.6% | -1.2 | +20.2% / +20.9% | 30 / 18 | 3 / 2 |
| public_02_incidents_s2 | +23.7% | +22.7% | +1.1 | +21.6% / +20.7% | 34 / 23 | 2 / 4 |
| r1_shuffled_truth | +25.0% | +22.3% | +2.7 | +18.5% / +17.3% | 31 / 18 | 4 / 4 |
| r1_shuffled_truth_s2 | +26.0% | +25.0% | +1.0 | +18.1% / +16.9% | 27 / 17 | 4 / 3 |
| r2_strict_policy | +23.5% | +23.5% | +0.0 | +20.5% / +20.5% | 17 / 17 | 4 / 4 |
| r2_strict_policy_s2 | +23.0% | +23.0% | +0.0 | +18.7% / +18.7% | 11 / 11 | 2 / 2 |
| r3_null_effects | +12.0% | +10.0% | +2.0 | +10.8% / +9.9% | 31 / 15 | 0 / 0 |
| r3_null_effects_s2 | +9.5% | +10.6% | -1.0 | +8.5% / +9.6% | 27 / 16 | 0 / 0 |
| r4_decay_heavy | +12.3% | +8.9% | +3.4 | +10.0% / +9.3% | 27 / 19 | 2 / 1 |
| r4_decay_heavy_s2 | +13.0% | +13.5% | -0.5 | +9.8% / +10.4% | 27 / 17 | 2 / 0 |
| r5_low_credits | +14.6% | +14.5% | +0.1 | +10.0% / +10.8% | 27 / 18 | 2 / 3 |
| r5_low_credits_s2 | +16.0% | +14.2% | +1.8 | +12.2% / +10.3% | 32 / 19 | 4 / 2 |
| r6_odd_shapes | +20.2% | +17.6% | +2.6 | +16.3% / +13.4% | 24 / 15 | 1 / 1 |
| r6_odd_shapes_s2 | +15.8% | +12.8% | +3.0 | +13.7% / +11.7% | 25 / 15 | 0 / 0 |

**Paired mean difference: +0.93 pp (SE 0.37, t = 2.48, n = 16).** Decision errors: 0 in both arms.

Reading it:
* `r2_strict_policy` is identical in both arms by design — no auto-apply there, so the feature never runs (built-in sanity check).
* Within each run the experiment's own daily test is under-powered (public_01: |z| ≤ 1.04, stopped at day 5 with "no evidence");
  pooled across 16 runs the small benefit becomes detectable. The in-run rule stays conservative on purpose: it removes
  preferences when a single run cannot show a benefit.
* Cost: ~10 extra auto-applied schedule refreshes per run (neutral in the grader: schedule does not change engagement or
  caller-ID health). Harmful counts differ only by noise (they come from variant changes, not schedule).
* Decision: keep it **on** by default. `OUTCOMELOOP_PERSON_TIME=0` turns it off.
