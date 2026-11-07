# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.395 | +15.8% | 0.266 | +8.9% | 0.527 | +5.3% | 40% | 443 (408) |
| arav_kyc_1 | 0.505 | +42.5% | 0.274 | +27.9% | 0.628 | +5.4% | 33% | 432 (370) |
| arav_renewal_0 | 0.486 | +20.8% | 0.287 | +8.7% | 0.598 | +10.1% | 48% | 465 (440) |
| kest_cancel_2 | 0.402 | +18.7% | 0.266 | +9.5% | 0.533 | +6.9% | 49% | 413 (411) |
| kest_kyc_1 | 0.501 | +41.9% | 0.274 | +28.3% | 0.623 | +4.9% | 30% | 462 (339) |
| kest_renewal_0 | 0.483 | +20.9% | 0.287 | +8.9% | 0.594 | +9.5% | 48% | 466 (433) |
| nort_cancel_2 | 0.404 | +19.4% | 0.266 | +9.6% | 0.537 | +7.6% | 51% | 410 (393) |
| nort_kyc_1 | 0.504 | +42.3% | 0.273 | +28.0% | 0.629 | +5.6% | 33% | 449 (323) |
| nort_renewal_0 | 0.480 | +18.7% | 0.286 | +8.4% | 0.595 | +8.7% | 49% | 439 (411) |
| tide_cancel_2 | 0.406 | +19.6% | 0.267 | +9.3% | 0.535 | +7.2% | 49% | 441 (407) |
| tide_kyc_1 | 0.415 | +17.4% | 0.236 | +10.1% | 0.616 | +4.0% | 20% | 375 (356) |
| tide_renewal_0 | 0.484 | +20.7% | 0.284 | +7.7% | 0.596 | +9.8% | 42% | 463 (438) |
| ALL | 0.455 | +24.8% | 0.272 | +13.2% | 0.584 | +7.5% | 41% | 5258 (4729) |

## Changes applied by the controller

82 applied — neutral: 43, beneficial: 38, harmful: 1

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
- tide_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.042 → **beneficial**
- arav_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.069 → **beneficial**
- nort_renewal_0 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v5 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.050 → **beneficial**
- arav_cancel_2 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.055 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.083 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v6 (controller_approved) dims=['voice'] engageΔ=+0.061 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v8 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.082 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v5 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.104 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.467 → **beneficial**
- arav_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.486 → **beneficial**
- kest_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.530 → **beneficial**
- nort_renewal_0 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v6 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v8 (controller_approved) dims=['voice'] engageΔ=+0.024 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v7 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.033 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.063 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.064 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.063 didΔ=+0.450 → **beneficial**
- kest_kyc_1 v5 (controller_approved) dims=['voice'] engageΔ=+0.029 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v11 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v10 (controller_approved) dims=['welcome_message'] engageΔ=-0.036 didΔ=+0.000 → **harmful**
- arav_cancel_2 v10 (controller_approved) dims=['welcome_message'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 36,
  "decisions": {
    "approved": 35,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 35,
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
    "arav_kyc_1": 2,
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
    "3": 0.851,
    "4": 0.849
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.851,
    "4": 0.85
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.85,
    "4": 0.194
  },
  "tide_renewal_0:welcome_message=W3": {
    "4": 0.851
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0