# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.398 | +16.7% | 0.266 | +9.0% | 0.531 | +6.1% | 49% | 453 (408) |
| arav_kyc_1 | 0.502 | +41.8% | 0.275 | +28.4% | 0.621 | +4.3% | 27% | 431 (370) |
| arav_renewal_0 | 0.486 | +20.8% | 0.286 | +8.3% | 0.600 | +10.5% | 51% | 434 (440) |
| kest_cancel_2 | 0.381 | +12.6% | 0.260 | +6.7% | 0.524 | +5.0% | 36% | 430 (411) |
| kest_kyc_1 | 0.503 | +42.3% | 0.274 | +28.2% | 0.626 | +5.4% | 33% | 427 (339) |
| kest_renewal_0 | 0.478 | +19.7% | 0.285 | +8.3% | 0.593 | +9.3% | 46% | 460 (433) |
| nort_cancel_2 | 0.396 | +16.8% | 0.265 | +9.5% | 0.528 | +5.8% | 39% | 418 (393) |
| nort_kyc_1 | 0.502 | +41.9% | 0.273 | +28.2% | 0.628 | +5.5% | 33% | 408 (323) |
| nort_renewal_0 | 0.478 | +18.1% | 0.286 | +8.4% | 0.592 | +8.0% | 47% | 478 (411) |
| tide_cancel_2 | 0.401 | +18.3% | 0.265 | +8.5% | 0.536 | +7.4% | 48% | 403 (407) |
| tide_kyc_1 | 0.448 | +26.8% | 0.251 | +17.1% | 0.618 | +4.4% | 20% | 433 (356) |
| tide_renewal_0 | 0.477 | +19.1% | 0.284 | +7.3% | 0.589 | +8.5% | 41% | 461 (438) |
| ALL | 0.454 | +24.4% | 0.273 | +13.4% | 0.583 | +7.2% | 39% | 5236 (4729) |

## Changes applied by the controller

55 applied — neutral: 15, beneficial: 39, harmful: 1

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
- arav_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.050 → **beneficial**
- kest_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.052 → **beneficial**
- arav_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.042 → **beneficial**
- nort_cancel_2 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.063 → **beneficial**
- kest_cancel_2 v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.011 → **neutral**
- kest_cancel_2 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.007 → **neutral**
- tide_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.060 didΔ=+0.045 → **beneficial**
- tide_renewal_0 v5 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.041 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v5 (controller_approved) dims=['voice'] engageΔ=+0.061 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v7 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.076 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v7 (controller_approved) dims=['voice'] engageΔ=+0.062 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v5 (controller_approved) dims=['voice'] engageΔ=+0.061 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.083 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.082 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.505 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.555 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.559 → **beneficial**
- arav_cancel_2 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v6 (controller_approved) dims=['voice'] engageΔ=+0.024 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v8 (controller_approved) dims=['welcome_message'] engageΔ=-0.007 didΔ=+0.000 → **neutral**
- tide_cancel_2 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.110 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.513 → **beneficial**
- kest_renewal_0 v6 (controller_approved) dims=['voice'] engageΔ=+0.025 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.064 didΔ=+0.004 → **beneficial**
- kest_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.064 didΔ=+0.005 → **beneficial**
- arav_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.027 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.064 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v7 (controller_approved) dims=['welcome_message'] engageΔ=-0.014 didΔ=+0.000 → **harmful**

## Governance

```
{
  "approval_requests": 41,
  "decisions": {
    "approved": 37,
    "rejected": 3,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 3
  },
  "applied_via_approval": 37,
  "auto_applied": 18,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_cancel_2": 2,
    "arav_cancel_2": 2,
    "tide_cancel_2": 2,
    "nort_renewal_0": 2,
    "nort_kyc_1": 1,
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
    "3": 0.849,
    "4": 0.622
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.851,
    "4": 0.852
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.852,
    "4": 0.849
  },
  "tide_renewal_0:welcome_message=W3": {
    "4": 0.85
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0