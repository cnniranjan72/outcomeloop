# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.385 | +12.7% | 0.266 | +9.0% | 0.513 | +2.6% | 24% | 465 (408) |
| arav_kyc_1 | 0.508 | +43.6% | 0.276 | +28.5% | 0.628 | +5.5% | 33% | 425 (370) |
| arav_renewal_0 | 0.485 | +20.5% | 0.287 | +8.8% | 0.597 | +9.8% | 50% | 466 (440) |
| kest_cancel_2 | 0.390 | +15.1% | 0.267 | +9.7% | 0.518 | +3.9% | 26% | 425 (411) |
| kest_kyc_1 | 0.509 | +44.1% | 0.276 | +28.8% | 0.629 | +5.8% | 33% | 422 (339) |
| kest_renewal_0 | 0.492 | +23.1% | 0.289 | +9.7% | 0.597 | +10.1% | 49% | 464 (433) |
| nort_cancel_2 | 0.403 | +19.0% | 0.266 | +9.7% | 0.536 | +7.4% | 49% | 447 (393) |
| nort_kyc_1 | 0.504 | +42.4% | 0.274 | +28.3% | 0.628 | +5.5% | 33% | 443 (323) |
| nort_renewal_0 | 0.484 | +19.6% | 0.286 | +8.7% | 0.597 | +8.9% | 49% | 437 (411) |
| tide_cancel_2 | 0.404 | +19.1% | 0.265 | +8.6% | 0.538 | +7.7% | 52% | 441 (407) |
| tide_kyc_1 | 0.411 | +16.4% | 0.235 | +9.7% | 0.613 | +3.6% | 17% | 387 (356) |
| tide_renewal_0 | 0.477 | +19.0% | 0.283 | +7.2% | 0.590 | +8.8% | 37% | 453 (438) |
| ALL | 0.454 | +24.5% | 0.273 | +13.3% | 0.582 | +7.1% | 38% | 5275 (4729) |

## Changes applied by the controller

83 applied — neutral: 43, beneficial: 39, harmful: 1

- nort_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.010 → **neutral**
- nort_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- kest_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.010 → **neutral**
- kest_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- arav_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.010 → **neutral**
- arav_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- tide_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.010 → **neutral**
- tide_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- nort_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.053 → **beneficial**
- kest_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.053 → **beneficial**
- kest_cancel_2 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.023 → **beneficial**
- arav_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.053 → **beneficial**
- tide_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- nort_cancel_2 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- nort_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.024 → **beneficial**
- tide_cancel_2 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=-0.003 didΔ=+0.035 → **beneficial**
- arav_cancel_2 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=-0.003 didΔ=+0.036 → **beneficial**
- kest_cancel_2 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=-0.003 didΔ=+0.011 → **neutral**
- nort_cancel_2 v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.011 → **neutral**
- nort_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.055 → **beneficial**
- kest_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.058 → **beneficial**
- tide_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.042 → **beneficial**
- arav_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.069 → **beneficial**
- nort_renewal_0 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.050 → **beneficial**
- tide_cancel_2 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.080 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.082 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v8 (controller_approved) dims=['voice'] engageΔ=+0.062 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.026 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.057 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.110 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v5 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.531 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.555 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.570 → **beneficial**
- nort_renewal_0 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v6 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v10 (controller_approved) dims=['welcome_message'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v8 (controller_approved) dims=['voice'] engageΔ=+0.024 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.063 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v7 (controller_approved) dims=['welcome_message'] engageΔ=+0.083 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.064 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.063 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v11 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v9 (controller_approved) dims=['voice'] engageΔ=+0.025 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['voice', 'caller_id'] engageΔ=+0.030 didΔ=+0.569 → **beneficial**
- nort_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v10 (controller_approved) dims=['welcome_message'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.033 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v10 (controller_approved) dims=['welcome_message'] engageΔ=-0.016 didΔ=+0.000 → **harmful**

## Governance

```
{
  "approval_requests": 37,
  "decisions": {
    "approved": 36,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 36,
  "auto_applied": 47,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_cancel_2": 2,
    "arav_cancel_2": 2,
    "tide_cancel_2": 2,
    "nort_renewal_0": 2,
    "nort_kyc_1": 2,
    "kest_renewal_0": 1,
    "kest_kyc_1": 1,
    "kest_cancel_2": 1,
    "arav_renewal_0": 2,
    "arav_kyc_1": 1,
    "tide_renewal_0": 2,
    "tide_kyc_1": 1
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
  "nort_renewal_0:welcome_message=W3": {
    "3": 0.847,
    "4": 0.847
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.848,
    "4": 0.851
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.849,
    "4": 0.585
  },
  "tide_renewal_0:welcome_message=W3": {
    "4": 0.848
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0