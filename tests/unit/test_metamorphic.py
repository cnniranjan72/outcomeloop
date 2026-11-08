"""Metamorphic tests: transformations of the input that must not change a decision (or must change it in a known
direction). They catch errors example-based tests miss. Deterministic: exact counts via helpers.add_calls."""
import random

from helpers import add_calls
from outcomeloop.config import Settings
from outcomeloop.detectors import did_health
from outcomeloop.experiments import Experiment, ExperimentEngine

WF, VER, DAY = 1, 2, 1440
NOW = 5 * DAY
GUARD = {"margin": 0.02}


def exp(arms=("V1", "V2", "V3"), n_plan=2000):
    k = len(arms) - 1
    return Experiment(experiment_id="e1", wf=WF, dim="voice", arms=list(arms), incumbent=arms[0],
                      design={arms[0]: 0.6, **{a: round(0.4 / k, 4) for a in arms[1:]}}, status="running",
                      start_minute=0, start_version=VER, versions=[VER], n_plan=n_plan, p_base=0.4)


def look(db, e=None, final=True):
    return ExperimentEngine(db, Settings()).look(e or exp(), NOW, [], GUARD, final_due=final)


def test_baseline_drift_shared_by_all_arms_creates_no_winner(db):
    # every arm loses the same 10 points in the second half (campaign mix, season): the arms still tie
    for v, n in (("V1", 3000), ("V2", 1000), ("V3", 1000)):
        add_calls(db, WF, n * 3, n, n // 2, minute=0, spread=2 * DAY, voice=v, cfg_ver=VER)              # 0.50
        add_calls(db, WF, n * 3, n, n * 4 // 10, minute=2 * DAY, spread=2 * DAY, voice=v, cfg_ver=VER)   # 0.40
    r = look(db)
    assert r["action"] != "promote" and all(abs(a["z"]) < 0.01 for a in r["arms"].values())


def test_population_shift_applied_to_every_arm_creates_no_winner(db):
    # the mix moves from age 60+ (engaged 0.6) to 18-30 (engaged 0.3) for everyone at once: still no difference
    for v, n in (("V1", 3000), ("V2", 1000)):
        add_calls(db, WF, n * 3, n, n * 6 // 10, minute=0, spread=2 * DAY, voice=v, cfg_ver=VER, age="60+")
        add_calls(db, WF, n * 3, n, n * 3 // 10, minute=2 * DAY, spread=2 * DAY, voice=v, cfg_ver=VER, age="18-30")
    assert look(db, exp(arms=("V1", "V2")))["action"] != "promote"


def test_unrelated_workflow_traffic_does_not_change_this_workflows_look(db):
    add_calls(db, WF, 9000, 3000, 1200, spread=NOW, voice="V1", cfg_ver=VER)
    add_calls(db, WF, 3000, 1000, 500, spread=NOW, voice="V2", cfg_ver=VER)
    before = look(db, exp(arms=("V1", "V2")))
    add_calls(db, 7, 30000, 10000, 9000, spread=NOW, voice="V1", cfg_ver=VER)      # another workflow, same codes
    after = look(db, exp(arms=("V1", "V2")))
    assert before["arms"] == after["arms"] and before["action"] == after["action"]


def test_more_data_with_no_difference_never_buys_a_winner(db):
    for scale in (1, 10, 50):
        db.x("DELETE FROM calls")
        db.x("DELETE FROM arm_hour")
        add_calls(db, WF, 900 * scale, 300 * scale, 120 * scale, spread=NOW, voice="V1", cfg_ver=VER)
        add_calls(db, WF, 300 * scale, 100 * scale, 40 * scale, spread=NOW, voice="V2", cfg_ver=VER)
        assert look(db, exp(arms=("V1", "V2")))["action"] != "promote", scale


def test_engagement_changes_never_move_caller_id_health(db):
    # caller-ID health is a pickup question; changing who stayed on the call must not change it
    opts = ["D1", "D2"]
    add_calls(db, 1, 2000, 600, 300, minute=NOW - 300, spread=280, did="D1")
    add_calls(db, 1, 2000, 300, 150, minute=NOW - 300, spread=280, did="D2")
    a = did_health(db, 1, opts, NOW, Settings())
    db.x("UPDATE calls SET eng = 1 - eng")                                           # flip every engagement outcome
    b = did_health(db, 1, opts, NOW, Settings())
    assert {d: a[d]["state"] for d in opts} == {d: b[d]["state"] for d in opts}
    assert a["D2"]["windows"]["fast"] == b["D2"]["windows"]["fast"]


def test_insertion_order_of_calls_does_not_matter(db, tmp_path):
    from outcomeloop.db import DB
    rows = [("V1", 3000, 1000, 400), ("V2", 1500, 500, 260), ("V3", 1500, 500, 200)]
    results = []
    for seed in (1, 2, 3):
        d = DB(tmp_path / f"s{seed}.db")
        order = rows[:]
        random.Random(seed).shuffle(order)
        for v, n, k, g in order:
            add_calls(d, WF, n, k, g, spread=NOW, voice=v, cfg_ver=VER)
        results.append(look(d)["arms"])
    assert results[0] == results[1] == results[2]
