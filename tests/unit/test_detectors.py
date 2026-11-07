import pytest

from outcomeloop.config import Settings
from outcomeloop.detectors import did_health, halluc_baseline, halluc_spike, kpi_drift

from helpers import add_calls

NOW = 2 * 1440
RECENT = NOW - 300          # inside both the 6h and 24h windows
OPTS = ["D1", "D2", "D3", "D4", "D5"]


def _dids(db, spec, minute=RECENT):
    with db.tx():
        for did, n, k in spec:
            add_calls(db, 1, n, k, minute=minute, spread=280, did=did)


def test_did_health_degraded_healthy_unknown(db):
    s = Settings()
    _dids(db, [("D1", 2000, 600), ("D2", 1000, 105),   # D2 at 0.35x the pickup of the others
               ("D3", 2000, 600), ("D4", 60, 18)])       # D4: too few dials to judge; D5 never dialled
    h = did_health(db, 1, OPTS, NOW, s)
    assert h["D2"]["state"] == "degraded"
    assert h["D2"]["windows"]["fast"]["ratio"] == pytest.approx(0.35, abs=0.01)
    assert h["D1"]["state"] == h["D3"]["state"] == "healthy"
    assert h["D4"]["state"] == "unknown" and h["D5"]["state"] == "unknown"
    assert h["D5"]["windows"]["slow"]["dials"] == 0


def test_did_health_equal_pickup_is_healthy_not_degraded(db):
    _dids(db, [("D1", 800, 240), ("D2", 800, 240), ("D3", 800, 240)])
    h = did_health(db, 1, ["D1", "D2", "D3"], NOW, Settings())
    assert {v["state"] for v in h.values()} == {"healthy"}


def test_did_health_small_noisy_dip_is_not_degraded(db):
    # 10% relative dip on 400 dials: well inside noise (z ~ -0.9), must not trigger a rotation
    _dids(db, [("D1", 2000, 600), ("D2", 400, 108)])
    h = did_health(db, 1, ["D1", "D2"], NOW, Settings())
    assert h["D2"]["state"] != "degraded"


def test_did_health_ignores_data_outside_windows(db):
    _dids(db, [("D1", 2000, 600), ("D2", 1000, 105)], minute=NOW - 3 * 1440)   # 3 days old
    h = did_health(db, 1, ["D1", "D2"], NOW, Settings())
    assert h["D2"]["state"] == "unknown"


def test_did_health_needs_min_dials_even_when_terrible(db):
    _dids(db, [("D1", 2000, 600), ("D2", 120, 0)])     # 0% pickup but only 120 dials (< 300)
    h = did_health(db, 1, ["D1", "D2"], NOW, Settings())
    assert h["D2"]["state"] != "degraded"


# ------------------------------------------------------------------ hallucination spike
def _prompt_calls(db, n, flags, prompt="P4", minute=RECENT):
    add_calls(db, 1, n, n, minute=minute, spread=280, prompt=prompt, flags=flags)


def test_halluc_spike_fires_on_4x_rate_with_enough_calls(db):
    _prompt_calls(db, 1000, 40)
    r = halluc_spike(db, 1, "P4", NOW - 1440, NOW, 0.01, Settings())
    assert r["fired"] and r["connected"] == 1000 and r["flag_rate"] == pytest.approx(0.04)
    assert r["z"] > 3.5


def test_halluc_spike_quiet_on_baseline_noise(db):
    _prompt_calls(db, 1000, 12)                        # 1.2% vs 1.0% reference
    assert not halluc_spike(db, 1, "P4", NOW - 1440, NOW, 0.01, Settings())["fired"]


def test_halluc_spike_needs_population_not_anecdotes(db):
    _prompt_calls(db, 100, 40)                         # 40% flagged, but only 100 connected calls
    r = halluc_spike(db, 1, "P4", NOW - 1440, NOW, 0.01, Settings())
    assert not r["fired"] and r["flag_rate"] == pytest.approx(0.4)


def test_halluc_spike_ratio_without_significance_does_not_fire(db):
    _prompt_calls(db, 300, 5)                          # 1.67x reference but z ~ 1.2
    r = halluc_spike(db, 1, "P4", NOW - 1440, NOW, 0.01, Settings())
    assert r["flag_rate"] > 1.5 * 0.01 and not r["fired"]


def test_halluc_spike_only_counts_current_prompt_since_change(db):
    _prompt_calls(db, 1000, 40, prompt="P1")           # another prompt's flags are irrelevant
    _prompt_calls(db, 1000, 40, prompt="P4", minute=NOW - 1000)   # before the prompt change at NOW-600
    _prompt_calls(db, 400, 4, prompt="P4", minute=NOW - 500)
    r = halluc_spike(db, 1, "P4", NOW - 600, NOW, 0.01, Settings())
    assert r["connected"] == 400 and not r["fired"]


def test_halluc_baseline_per_prompt(db):
    _prompt_calls(db, 1000, 10, prompt="P1", minute=-1440)
    _prompt_calls(db, 500, 25, prompt="P4", minute=-1440)
    add_calls(db, 1, 300, 0, minute=-1440, prompt="P1")         # unconnected calls don't dilute the rate
    b = halluc_baseline(db, 1, 0)
    assert b["P1"]["connected"] == 1000 and b["P1"]["flag_rate"] == pytest.approx(0.01)
    assert b["P4"]["flag_rate"] == pytest.approx(0.05)


def test_kpi_drift_alerts_on_real_drop_only(db):
    add_calls(db, 1, 7000, 2100, 1050, minute=NOW - 8 * 1440, spread=7 * 1440 - 1)   # 30% pickup baseline
    add_calls(db, 1, 1500, 300, 150, minute=NOW - 1440, spread=1439)                  # 20% pickup today
    d = kpi_drift(db, 1, NOW, Settings())
    assert "pickup_drop" in d["alerts"]
    assert "engagement_drop" not in d["alerts"]                       # 50% engagement both periods
