"""Every tunable constant, with the reason it has the value it has.

Nothing here is fitted to public-scenario ground truth. Values come from error-rate arithmetic (see
docs/DESIGN_DECISIONS.md) or from the governance policy each workflow publishes via the API.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    sim_url: str = "http://127.0.0.1:8700"
    db_path: str = "state/outcomeloop.db"
    tick_minutes: int = 15             # advance one sim tick at a time: 2h apply windows, incident speed
    decision_every_minutes: int = 60   # planner/detector cadence (sim time)
    http_timeout_s: float = 120.0
    http_retries: int = 5

    # ---- experiments (C6)
    alpha: float = 0.05                # family-wise one-sided false-winner rate per (workflow, dimension)
    power: float = 0.80
    mde_rel: float = 0.10              # minimum detectable relative lift we plan for
    max_experiment_days: float = 5.0   # horizon; at the horizon "no evidence → keep incumbent"
    challenger_share: float = 0.40     # total traffic share for challengers while exploring
    holdout_share: float = 0.15        # previous incumbent kept after promotion, for decay detection
    min_arm_connected_for_look: int = 150
    harm_z: float = 1.645              # drop a challenger / protect a cohort when worse at one-sided 5%
    harm_min_connected: int = 200
    decay_z: float = 2.33              # lift now vs lift at promotion, one-sided 1%
    decay_window_minutes: int = 1440
    decay_min_connected: int = 120
    rollback_blacklist_days: float = 7.0    # a decayed option is not re-tested for a week
    harm_blacklist_days: float = 14.0       # an option dropped as significantly worse: two weeks
    no_winner_cooldown_days: float = 3.0    # a dimension with no winner is not re-tested immediately

    # ---- cohorts (C2/C3)
    min_cohort_share: float = 0.10
    max_cohorts: int = 6
    schedule_gamma: float = 2.0
    schedule_w_min: float = 0.25
    schedule_w_max: float = 4.0
    schedule_eb_strength: float = 200.0   # pseudo-dials of shrinkage toward the workflow hour profile

    # ---- caller ID (C5)
    did_degraded_ratio: float = 0.85
    did_degraded_z: float = 3.5
    did_min_dials: int = 300
    did_healthy_ratio: float = 0.92
    did_healthy_min_dials: int = 150
    did_probe_share: float = 0.05
    did_reprobe_share: float = 0.02     # a number that was degraded risks less traffic than an unknown one
    did_probe_hours: float = 24.0       # a probe is time-boxed: healthy by then, or back to rest
    did_fast_window_minutes: int = 360
    did_slow_window_minutes: int = 1440
    did_long_window_minutes: int = 4320   # healthy-only: lets a 5% probe on a small workflow reach n
    did_min_tv_change: float = 0.05     # don't churn config for tiny re-balancing

    # ---- hallucination (C8)
    halluc_ratio: float = 1.5
    halluc_z: float = 3.5
    halluc_min_connected: int = 250
    halluc_window_minutes: int = 240
    validation_n: int = 300
    credit_incident_reserve: float = 0.40
    known_good_min_connected: int = 1000

    # ---- KPI drift alerts
    drift_rel: float = 0.05
    drift_z: float = 3.0

    # ---- governance (C9)
    supervisor_lock_hours: float = 48.0
    reject_cooldown_hours: float = 4.0
    ramp_min_gap_minutes: int = 60
    ramp_daily_shift_multiple: float = 3.0
    customer_facing_dims: tuple = ("welcome_message", "voice", "prompt_version")
    tenant_preferences: dict = field(default_factory=dict)

    @classmethod
    def load(cls, sim_url: str | None = None) -> "Settings":
        s = cls()
        if sim_url:
            s.sim_url = sim_url
        s.db_path = os.environ.get("OUTCOMELOOP_DB", s.db_path)
        pref = Path(os.environ.get("OUTCOMELOOP_TENANT_PREFS", "config/tenant_preferences.json"))
        if pref.exists():
            s.tenant_preferences = json.loads(pref.read_text())
        return s

    def tenant_pref(self, tenant_id: str) -> dict:
        return self.tenant_preferences.get(tenant_id, {})
