# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.396 | +16.1% | 0.265 | +8.6% | 0.529 | +5.8% | 40% | 438 (408) |
| arav_kyc_1 | 0.502 | +41.9% | 0.275 | +28.1% | 0.624 | +4.8% | 33% | 413 (370) |
| arav_renewal_0 | 0.482 | +19.9% | 0.287 | +8.7% | 0.593 | +9.2% | 47% | 434 (440) |
| kest_cancel_2 | 0.398 | +17.6% | 0.265 | +8.9% | 0.532 | +6.7% | 46% | 445 (411) |
| kest_kyc_1 | 0.509 | +44.1% | 0.276 | +29.1% | 0.629 | +5.8% | 33% | 440 (339) |
| kest_renewal_0 | 0.488 | +22.0% | 0.289 | +9.6% | 0.596 | +9.9% | 51% | 438 (433) |
| nort_cancel_2 | 0.394 | +16.4% | 0.265 | +9.2% | 0.528 | +5.8% | 38% | 427 (393) |
| nort_kyc_1 | 0.501 | +41.5% | 0.274 | +28.6% | 0.624 | +4.8% | 27% | 447 (323) |
| nort_renewal_0 | 0.478 | +18.1% | 0.284 | +7.9% | 0.594 | +8.4% | 49% | 467 (411) |
| tide_cancel_2 | 0.385 | +13.5% | 0.265 | +8.7% | 0.515 | +3.2% | 32% | 408 (407) |
| tide_kyc_1 | 0.407 | +15.2% | 0.234 | +9.0% | 0.611 | +3.2% | 17% | 409 (356) |
| tide_renewal_0 | 0.479 | +19.5% | 0.283 | +7.1% | 0.593 | +9.3% | 41% | 452 (438) |
| ALL | 0.452 | +23.8% | 0.272 | +13.1% | 0.581 | +6.9% | 38% | 5218 (4729) |

## Changes applied by the controller

51 applied — neutral: 14, beneficial: 36, harmful: 1

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
- arav_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.042 → **beneficial**
- tide_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.069 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.050 → **beneficial**
- arav_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.053 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.085 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.108 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.085 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.108 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.083 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v5 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.520 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.525 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.559 → **beneficial**
- tide_renewal_0 v6 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v6 (controller_approved) dims=['voice'] engageΔ=+0.025 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.053 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v7 (controller_approved) dims=['welcome_message'] engageΔ=-0.008 didΔ=+0.000 → **neutral**
- kest_cancel_2 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v7 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.064 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.064 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.063 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.022 didΔ=+0.546 → **beneficial**
- nort_renewal_0 v6 (controller_approved) dims=['welcome_message'] engageΔ=-0.029 didΔ=+0.000 → **harmful**
- arav_cancel_2 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 37,
  "decisions": {
    "approved": 35,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 35,
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
    "3": 0.848,
    "4": 0.338
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.85,
    "4": 0.851
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.852,
    "4": 0.845
  },
  "tide_renewal_0:welcome_message=W3": {
    "4": 0.852
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0