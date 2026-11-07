"""Generate our own "hidden-like" scenarios: same schema as the public ones, different truth, policies and
incidents. Test tooling only — the controller never reads scenario files.

    python scripts/make_robustness_scenarios.py      # writes tests/robustness/*.yaml

Each variant targets a failure mode a hidden scenario could expose:
  r1_shuffled_truth   different winners/losers, different seed (does learning generalise?)
  r2_strict_policy    no auto-apply anywhere, slow approvers, short TTL, caller ID flagged on a workflow that can
                      only change via approval, unsafe supervisor prompt on Northwind (approval-only rescue)
  r3_null_effects     NO true variant effects at all (false-winner rate; every applied variant change is noise)
  r4_decay_heavy      several winners that decay quickly (decay detection and rollback speed)
  r5_low_credits      12 credits, two prompt incidents (credit discipline; LLM must not burn the budget)
  r6_odd_shapes       single-option dims, 5 caller IDs two of them bad from the start, unusual language mix,
                      pickup-primary workflow with a tight guardrail, next_campaign_only everywhere
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "robustness"


def base() -> dict:
    return yaml.safe_load((ROOT / "scenarios" / "public_02_incidents.yaml").read_text(encoding="utf-8"))


def wf(sc, wid):
    return next(w for t in sc["tenants"] for w in t["workflows"] if w["id"] == wid)


def r1():
    sc = base()
    sc.update(name="r1_shuffled_truth", seed=1101)
    sc["effects"] = [
        {"workflow": "nw_renewal", "dim": "voice", "value": "V4", "mult": 1.15, "where": {"age_band": ["46-60", "60+"]}},
        {"workflow": "nw_renewal", "dim": "welcome_message", "value": "W2", "mult": 0.88},
        {"workflow": "nw_renewal", "dim": "welcome_message", "value": "W3", "mult": 1.09, "where": {"lang": ["en", "ta"]}},
        {"workflow": "nw_kyc", "dim": "voice", "value": "V2", "mult": 0.90},
        {"workflow": "nw_kyc", "dim": "welcome_message", "value": "W2", "mult": 1.12, "where": {"lang": ["hi"]}},
        {"workflow": "ks_cancel", "dim": "voice", "value": "V2", "mult": 1.18},
        {"workflow": "ks_cancel", "dim": "welcome_message", "value": "W3", "mult": 1.07, "where": {"city_tier": ["2", "3"]}},
    ]
    sc["incidents"] = [
        {"type": "did_flagged", "workflow": "nw_renewal", "did": "D1", "at": "D3 14:00", "base_health": 0.4},
        {"type": "supervisor_edit", "workflow": "ks_cancel", "at": "D5 16:00", "patch": {"prompt_version": "P4"},
         "note": "supervisor ships the persuasive prompt"},
    ]
    return sc


def r2():
    sc = base()
    sc.update(name="r2_strict_policy", seed=2202)
    for t in sc["tenants"]:
        for w in t["workflows"]:
            g = w["governance"]
            g["auto_apply"] = {"enabled": False, "allowed_dims": [], "max_shift": 0}
            g["approver_latency_minutes"] = [90, 420]
            g["proposal_ttl_hours"] = 10
            g["max_requests_per_24h"] = 2
            g["base_reject_rate"] = 0.2
    sc["incidents"] = [
        {"type": "did_flagged", "workflow": "nw_kyc", "did": "D1", "at": "D2 11:00", "base_health": 0.3},
        {"type": "supervisor_edit", "workflow": "nw_renewal", "at": "D4 10:30", "patch": {"prompt_version": "P4"},
         "note": "supervisor ships the persuasive prompt on Northwind"},
        {"type": "supervisor_edit", "workflow": "ks_cancel", "at": "D6 12:00",
         "patch": {"allocations": {"default": {"caller_id": {"D3": 1}}}}, "note": "supervisor pins a caller ID"},
    ]
    return sc


def r3():
    sc = base()
    sc.update(name="r3_null_effects", seed=3303, effects=[], incidents=[])
    return sc


def r4():
    sc = base()
    sc.update(name="r4_decay_heavy", seed=4404)
    dec = {"after_exposure_days": 1.5, "to_mult": 0.9, "over_days": 1}
    sc["effects"] = [
        {"workflow": "nw_renewal", "dim": "welcome_message", "value": "W2", "mult": 1.2, "decay": dec},
        {"workflow": "nw_renewal", "dim": "voice", "value": "V3", "mult": 1.15, "decay": dec},
        {"workflow": "ks_cancel", "dim": "voice", "value": "V4", "mult": 1.2, "decay": dec},
        {"workflow": "ks_cancel", "dim": "welcome_message", "value": "W2", "mult": 1.08},
        {"workflow": "nw_kyc", "dim": "voice", "value": "V2", "mult": 1.18, "decay": dec},
    ]
    sc["incidents"] = []
    return sc


def r5():
    sc = base()
    sc.update(name="r5_low_credits", seed=5505, credits=12)
    sc["incidents"] = [
        {"type": "supervisor_edit", "workflow": "ks_cancel", "at": "D2 12:00", "patch": {"prompt_version": "P2"}},
        {"type": "supervisor_edit", "workflow": "nw_renewal", "at": "D6 11:00", "patch": {"prompt_version": "P4"}},
    ]
    return sc


def r6():
    sc = base()
    sc.update(name="r6_odd_shapes", seed=6606)
    w = wf(sc, "nw_renewal")
    w["options"]["welcome_message"] = ["W1"]                      # nothing to test on welcome
    w["options"]["caller_id"] = ["D1", "D2", "D3", "D4", "D5"]
    w["did_base_health"] = {"D4": 0.5, "D5": 0.6}                 # two bad numbers before D0
    w["language_mix"] = {"kn": 0.4, "te": 0.3, "bn": 0.3}
    w["mid_flight"] = "next_campaign_only"
    k = wf(sc, "nw_kyc")
    k["objective"] = {"primary": "pickup_rate", "guardrail": {"engagement_rate_max_drop": 0.01}}
    k["options"]["voice"] = ["V1"]                                 # single voice
    c = wf(sc, "ks_cancel")
    c["mid_flight"] = "next_campaign_only"
    c["dialling_window"] = [11, 19]
    c["governance"]["approver_hours"] = [12, 16]
    sc["effects"] = [
        {"workflow": "nw_renewal", "dim": "voice", "value": "V2", "mult": 1.15, "where": {"lang": ["kn"]}},
        {"workflow": "nw_kyc", "dim": "welcome_message", "value": "W2", "mult": 1.1},
        {"workflow": "ks_cancel", "dim": "voice", "value": "V3", "mult": 1.12},
    ]
    sc["incidents"] = [{"type": "did_flagged", "workflow": "ks_cancel", "did": "D1", "at": "D3 12:00", "base_health": 0.35}]
    return sc


def public(name):
    def f():
        return yaml.safe_load((ROOT / "scenarios" / f"{name}.yaml").read_text(encoding="utf-8"))
    return f


def main():
    import os
    OUT.mkdir(parents=True, exist_ok=True)
    reps = int(os.environ.get("SEED_REPLICAS", "1"))
    makers = [r1, r2, r3, r4, r5, r6]
    for rep in range(reps):
        for f in makers + ([public("public_01_dev"), public("public_02_incidents")] if rep else []):
            sc = f()
            if rep:   # same truth and policy, different random world: separates real effects from luck
                sc["name"] = f"{sc['name']}_s{rep + 1}"
                sc["seed"] = int(sc["seed"]) * 7 + rep
            p = OUT / f"{sc['name']}.yaml"
            with open(p, "w", encoding="utf-8", newline="\n") as fh:   # LF on every OS: no line-ending churn
                fh.write("# Generated by scripts/make_robustness_scenarios.py - our own test scenario, not a public one.\n"
                         + yaml.safe_dump(sc, sort_keys=False))
            print("wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
