# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.379 | +13.9% | 0.261 | +9.4% | 0.505 | +2.9% | 17% | 62 (47) |
| nw_kyc | 0.460 | +26.6% | 0.277 | +14.4% | 0.638 | +8.0% | 26% | 34 (21) |
| nw_renewal | 0.471 | +12.1% | 0.286 | +8.6% | 0.562 | +3.1% | 23% | 49 (42) |
| ALL | 0.427 | +15.9% | 0.273 | +10.1% | 0.552 | +4.2% | 22% | 145 (110) |

## Changes applied by the controller

16 applied — neutral: 4, beneficial: 12

- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.009 → **neutral**
- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.040 didΔ=+0.000 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.048 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.035 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.047 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.014 → **neutral**
- nw_renewal v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.021 → **beneficial**
- ks_cancel v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- nw_renewal v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.083 didΔ=+0.000 → **beneficial**
- ks_cancel v7 (controller_approved) dims=['welcome_message'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.261 → **beneficial**
- nw_renewal v7 (controller_approved) dims=['welcome_message'] engageΔ=+0.063 didΔ=+0.000 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['voice', 'caller_id'] engageΔ=+0.031 didΔ=+0.022 → **beneficial**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 12,
  "decisions": {
    "approved": 10,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 10,
  "auto_applied": 6,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 1,
    "ks_cancel": 1
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "3": 0.846,
    "4": 0.854,
    "5": 0.551,
    "6": 0.0,
    "7": 0.0
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0