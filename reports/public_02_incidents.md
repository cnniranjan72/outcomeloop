# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.365 | +47.5% | 0.252 | +37.1% | 0.495 | +3.9% | 38% | 65 (330) |
| nw_kyc | 0.448 | +19.5% | 0.282 | +16.4% | 0.600 | +1.3% | 3% | 40 (31) |
| nw_renewal | 0.464 | +8.8% | 0.290 | +10.9% | 0.534 | -2.5% | 3% | 62 (55) |
| ALL | 0.416 | +24.4% | 0.271 | +22.1% | 0.530 | +0.1% | 23% | 167 (416) |

## Changes applied by the controller

18 applied — neutral: 4, beneficial: 12, harmful: 2

- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.018 → **neutral**
- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.013 didΔ=+0.000 → **beneficial**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.026 didΔ=+0.000 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.035 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.069 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.014 → **neutral**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=-0.016 didΔ=+0.036 → **harmful**
- nw_renewal v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.111 didΔ=+0.000 → **beneficial**
- ks_cancel v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.170 → **beneficial**
- ks_cancel v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.097 → **beneficial**
- ks_cancel v9 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.032 didΔ=+0.000 → **beneficial**
- nw_renewal v6 (controller_approved) dims=['voice'] engageΔ=+0.014 didΔ=+0.000 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.347 → **beneficial**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.092 didΔ=+0.000 → **beneficial**
- nw_renewal v9 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.011 didΔ=+0.000 → **harmful**
- nw_renewal v10 (controller_approved) dims=['voice'] engageΔ=+0.004 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 15,
  "decisions": {
    "approved": 11,
    "rejected": 3,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 3
  },
  "applied_via_approval": 11,
  "auto_applied": 7,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 2,
    "ks_cancel": 1
  }
}
```

## Incidents

```
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.118,
      "3": 0.0,
      "4": 0.0,
      "5": 0.0,
      "6": 0.0,
      "7": 0.0,
      "8": 0.0,
      "9": 0.0
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 60,
    "fixed_by": "controller_approved"
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D5 15:00"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "2": 0.871,
    "3": 0.846,
    "4": 0.835,
    "5": 0.846,
    "6": 0.373,
    "7": 0.0,
    "8": 0.0,
    "9": 0.0
  }
}
```

Credits used: 9 · validation runs: 3 · LLM fix calls: 0