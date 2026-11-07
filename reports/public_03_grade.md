# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.396 | +16.1% | 0.266 | +8.9% | 0.529 | +5.7% | 40% | 405 (408) |
| arav_kyc_1 | 0.503 | +42.2% | 0.274 | +27.5% | 0.627 | +5.3% | 34% | 482 (370) |
| arav_renewal_0 | 0.489 | +21.5% | 0.289 | +9.4% | 0.596 | +9.7% | 49% | 486 (440) |
| kest_cancel_2 | 0.391 | +15.4% | 0.266 | +9.3% | 0.522 | +4.6% | 34% | 449 (411) |
| kest_kyc_1 | 0.497 | +40.6% | 0.276 | +28.9% | 0.616 | +3.6% | 23% | 449 (339) |
| kest_renewal_0 | 0.484 | +21.1% | 0.287 | +9.0% | 0.595 | +9.7% | 50% | 481 (433) |
| nort_cancel_2 | 0.405 | +19.4% | 0.266 | +9.7% | 0.537 | +7.7% | 49% | 447 (393) |
| nort_kyc_1 | 0.505 | +42.6% | 0.274 | +28.4% | 0.628 | +5.4% | 33% | 432 (323) |
| nort_renewal_0 | 0.484 | +19.6% | 0.287 | +9.1% | 0.595 | +8.6% | 50% | 460 (411) |
| tide_cancel_2 | 0.391 | +15.2% | 0.265 | +8.5% | 0.523 | +4.7% | 31% | 397 (407) |
| tide_kyc_1 | 0.413 | +16.8% | 0.235 | +9.6% | 0.616 | +4.0% | 20% | 386 (356) |
| tide_renewal_0 | 0.473 | +18.0% | 0.282 | +6.9% | 0.588 | +8.4% | 37% | 422 (438) |
| ALL | 0.452 | +24.0% | 0.272 | +13.2% | 0.581 | +6.9% | 38% | 5296 (4729) |

## Changes applied by the controller

49 applied — neutral: 12, beneficial: 35, harmful: 2

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
- nort_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.025 → **beneficial**
- tide_cancel_2 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=-0.003 didΔ=+0.035 → **beneficial**
- arav_cancel_2 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=-0.003 didΔ=+0.036 → **beneficial**
- kest_cancel_2 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=-0.003 didΔ=+0.010 → **neutral**
- nort_cancel_2 v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.010 → **neutral**
- nort_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.055 → **beneficial**
- kest_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.058 → **beneficial**
- arav_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.042 → **beneficial**
- tide_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.069 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.050 → **beneficial**
- arav_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.053 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.104 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.075 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v5 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.040 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.521 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.526 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.560 → **beneficial**
- tide_renewal_0 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.082 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.053 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.063 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.063 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.064 didΔ=+0.459 → **beneficial**
- tide_renewal_0 v7 (controller_approved) dims=['voice'] engageΔ=+0.024 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.063 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v6 (controller_approved) dims=['welcome_message'] engageΔ=-0.015 didΔ=+0.000 → **harmful**
- tide_renewal_0 v8 (controller_approved) dims=['welcome_message'] engageΔ=-0.097 didΔ=+0.000 → **harmful**

## Governance

```
{
  "approval_requests": 36,
  "decisions": {
    "approved": 33,
    "rejected": 3,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 3
  },
  "applied_via_approval": 33,
  "auto_applied": 16,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_cancel_2": 1,
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
    "3": 0.852,
    "4": 0.848
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.851,
    "4": 0.852
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.851,
    "4": 0.603
  },
  "tide_renewal_0:welcome_message=W3": {
    "4": 0.517
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0