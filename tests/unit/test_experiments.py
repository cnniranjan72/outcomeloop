"""Experiment looks, promotion, guardrails, cohort harm, stability and decay on synthetic call rows."""
import copy

import pytest

from outcomeloop.cohorts import Cohort
from outcomeloop.config import Settings
from outcomeloop.experiments import Experiment, ExperimentEngine
from outcomeloop.stats import z_of

from helpers import add_calls

WF, VER = 1, 2
DAY = 1440
NOW = 5 * DAY
GUARD = {"margin": 0.02}


def exp(arms=("V1", "V2", "V3"), n_plan=2000, versions=(VER,), **kw) -> Experiment:
    arms = list(arms)
    k = len(arms) - 1
    design = {arms[0]: 0.6, **{a: round(0.4 / k, 4) for a in arms[1:]}}
    return Experiment(experiment_id="e1", wf=WF, dim="voice", arms=arms, incumbent=arms[0], design=design,
                      status="running", start_minute=0, start_version=VER, versions=list(versions), n_plan=n_plan,
                      p_base=0.4, **kw)


def arm(db, voice, conn, eng, *, dials=None, start=0, end=NOW, ver=VER, lang="hi"):
    add_calls(db, WF, dials if dials is not None else conn * 3, conn, eng, minute=start, spread=end - start,
              voice=voice, cfg_ver=ver, lang=lang)


@pytest.fixture()
def eng(db):
    return ExperimentEngine(db, Settings())


# ------------------------------------------------------------------ looks
def test_insufficient_sample_no_action(db, eng):
    arm(db, "V1", 100, 40)
    arm(db, "V2", 100, 60)
    arm(db, "V3", 100, 40)
    e = exp()
    res = eng.look(e, NOW, [], GUARD, final_due=False)
    assert res["action"] == "none"
    assert e.alpha_spent == 0 and e.t_prev == 0          # no alpha spent on a look that couldn't decide


def test_clear_winner_promoted_deterministically(db, eng):
    arm(db, "V1", 2000, 800)      # 0.40
    arm(db, "V2", 2000, 1000)     # 0.50
    arm(db, "V3", 2000, 960)      # 0.48 - also significant, but lower LCB
    res = eng.look(exp(), NOW, [], GUARD, final_due=True)
    assert res["action"] == "promote" and res["winner"] == "V2"
    assert set(res["significant"]) == {"V2", "V3"}
    # same data, same decision - including when the arm order is permuted
    again = eng.look(exp(), NOW, [], GUARD, final_due=True)
    perm = eng.look(exp(arms=("V1", "V3", "V2")), NOW, [], GUARD, final_due=True)
    assert again == res and perm["winner"] == "V2"


def test_promotion_plan_keeps_holdout(db, eng):
    arm(db, "V1", 2000, 800)
    arm(db, "V2", 2000, 1000)
    e = exp(arms=("V1", "V2"))
    res = eng.look(e, NOW, [], GUARD, final_due=True)
    eng.plan_promotion(e, res)
    assert e.status == "promoting" and e.winner == "V2"
    assert e.plan == {"default": {"V2": 0.85, "V1": 0.15}}
    assert e.promo["default"]["diff"] == pytest.approx(0.10)


def test_no_difference_at_horizon_keeps_incumbent(db, eng):
    for v in ("V1", "V2", "V3"):
        arm(db, v, 2000, 800)
    e = exp()
    res = eng.look(e, NOW, [], GUARD, final_due=True)
    assert res["action"] == "no_winner"
    eng.plan_no_winner(e)
    assert e.plan == {"default": {"V1": 1.0}} and e.status == "concluding"


def test_positive_trend_extends_once_then_concludes_within_alpha(db, eng):
    arm(db, "V1", 2000, 800)
    arm(db, "V2", 2000, 820)       # +1pt: not significant
    e = exp(arms=("V1", "V2"))
    r1 = eng.look(e, NOW, [], GUARD, final_due=True)
    assert r1["action"] == "extend" and e.extended and e.n_plan == 4000
    r2 = eng.look(e, 2 * NOW, [], GUARD, final_due=True)
    assert r2["action"] == "no_winner"
    assert e.alpha_spent <= Settings().alpha + 1e-12


def test_guardrail_blocks_winner_that_costs_pickup(db, eng):
    arm(db, "V1", 2000, 800, dials=6000)     # pickup 0.333
    arm(db, "V2", 2000, 1000, dials=7000)    # pickup 0.286: -4.8 points > 2-point margin
    e = exp(arms=("V1", "V2"), extended=True)
    res = eng.look(e, NOW, [], GUARD, final_due=True)
    assert res["guardrail_blocked"] == ["V2"] and res["significant"] == []
    assert res["action"] == "no_winner"


def test_harmful_challenger_dropped_before_horizon(db, eng):
    arm(db, "V1", 1000, 500)
    arm(db, "V2", 1000, 400)        # significantly worse
    arm(db, "V3", 1000, 500)
    e = exp(n_plan=10_000)
    res = eng.look(e, NOW, [], GUARD, final_due=False)
    assert res["action"] == "drop" and res["drop"] == ["V2"]
    eng.plan_drop(e, res["drop"])
    assert e.dropped == ["V2"] and "V2" not in e.design
    assert sum(e.design.values()) == pytest.approx(1.0, abs=1e-3)
    assert e.design["V1"] > e.design["V3"]                 # dropping only moves traffic back, keeps the shape


def test_harmful_challenger_dropped_even_while_others_underpowered(db, eng):
    arm(db, "V1", 1000, 500)
    arm(db, "V2", 1000, 400)
    arm(db, "V3", 50, 25)
    res = eng.look(exp(n_plan=10_000), NOW, [], GUARD, final_due=False)
    assert res["action"] == "drop" and res["drop"] == ["V2"]


def test_cohort_harm_check_keeps_incumbent_in_harmed_cohort(db, eng):
    arm(db, "V1", 3000, 1200)                 # hi: 0.40
    arm(db, "V2", 3000, 1650)                 # hi: 0.55
    arm(db, "V1", 400, 200, lang="ta")        # ta: 0.50
    arm(db, "V2", 400, 140, lang="ta")        # ta: 0.35 - the winner hurts this cohort
    cohorts = [Cohort("lang_ta", {"lang": ["ta"]})]
    e = exp(arms=("V1", "V2"))
    res = eng.look(e, NOW, cohorts, GUARD, final_due=True)
    assert res["action"] == "promote" and res["winner"] == "V2"
    assert res["cohort_check"]["lang_ta"]["keeps_incumbent"] is True
    eng.plan_promotion(e, res)
    assert e.plan["lang_ta"] == {"V1": 1.0}
    assert e.plan["default"] == {"V2": 0.85, "V1": 0.15}


def test_stability_blocks_winner_whose_recent_lift_vanished(db, eng):
    arm(db, "V1", 1600, 640, end=NOW - DAY)           # first 4 days: V2 much better
    arm(db, "V2", 1600, 880, end=NOW - DAY)
    arm(db, "V1", 400, 180, start=NOW - DAY)          # last 24h: V2 no better (novelty wore off)
    arm(db, "V2", 400, 170, start=NOW - DAY)
    res = eng.look(exp(arms=("V1", "V2")), NOW, [], GUARD, final_due=True)
    assert res["action"] != "promote"
    assert res["stability"]["V2"]["unstable"] is True
    assert res["stability"]["V2"]["recent_lift"] <= 0


def test_evidence_only_from_experiment_versions(db, eng):
    for v in ("V1", "V2"):
        arm(db, v, 2000, 800, ver=VER)
    arm(db, "V2", 5000, 4000, ver=7)                  # a different config version (e.g. supervisor's): ignored
    res = eng.look(exp(arms=("V1", "V2")), NOW, [], GUARD, final_due=True)
    assert res["arms"]["V2"]["connected"] == 2000
    assert res["action"] == "no_winner"


def test_arm_that_never_ran_cannot_win(db, eng):
    arm(db, "V1", 2000, 800)
    arm(db, "V2", 2000, 800)
    res = eng.look(exp(), NOW, [], GUARD, final_due=True)   # V3 has no calls
    assert res["arms"]["V3"]["connected"] == 0
    assert res["action"] in ("no_winner", "extend") and res.get("winner") is None


# ------------------------------------------------------------------ decay
def promoted(diff, se, cohorts_plan=None):
    e = exp(arms=("V1", "V2"), versions=(3,))
    e.status, e.promoted_minute, e.winner = "promoted", 0, "V2"
    e.plan = {"default": {"V2": 0.85, "V1": 0.15}, **(cohorts_plan or {})}
    e.promo = {"default": {"winner": "V2", "incumbent": "V1", "diff": diff, "se": se}}
    return e


def test_decay_detected_when_lift_collapses(db, eng):
    arm(db, "V2", 4000, 1600, start=NOW - DAY, ver=3)    # winner now 0.40
    arm(db, "V1", 1000, 400, start=NOW - DAY, ver=3)     # holdout 0.40: lift gone
    dc = eng.decay_check(promoted(0.10, 0.02), NOW, [])
    assert dc["decayed"] == ["default"]
    assert dc["scopes"]["default"]["lift_now"] == pytest.approx(0.0)


def test_decay_pooled_scope_with_cohorts_excludes_only_overridden_cohorts(db, eng):
    cohorts = [Cohort("lang_ta", {"lang": ["ta"]}), Cohort("lang_en", {"lang": ["en"]})]
    arm(db, "V2", 4000, 1600, start=NOW - DAY, ver=3)                # unmatched rows -> 'default' cohort
    arm(db, "V1", 1000, 400, start=NOW - DAY, ver=3)
    arm(db, "V2", 400, 300, start=NOW - DAY, ver=3, lang="ta")       # lang_ta has its own override: excluded
    arm(db, "V1", 400, 100, start=NOW - DAY, ver=3, lang="ta")
    e = promoted(0.10, 0.02, {"lang_ta": {"V1": 1.0}})
    dc = eng.decay_check(e, NOW, cohorts)
    assert dc["scopes"]["default"]["winner_connected"] == 4000
    assert dc["decayed"] == ["default"]


def test_decay_not_triggered_by_winners_curse_shrinkage(db, eng):
    # promoted at +10pt (se 3pt): an inflated estimate. Now +2pt on lots of data: smaller, but still positive.
    arm(db, "V2", 6000, 3120, start=NOW - DAY, ver=3)    # 0.52
    arm(db, "V1", 2000, 1000, start=NOW - DAY, ver=3)    # 0.50
    dc = eng.decay_check(promoted(0.10, 0.03), NOW, [])
    sc = dc["scopes"]["default"]
    assert sc["lift_now"] == pytest.approx(0.02)
    assert dc["decayed"] == []
    # the comparison against the raw point estimate WOULD have fired: the LCB correction is what prevents it
    se_now = (0.25 / 2000 + 0.2496 / 6000) ** 0.5
    raw_z = (0.02 - 0.10) / (se_now ** 2 + 0.03 ** 2) ** 0.5
    assert raw_z < -Settings().decay_z
    assert sc["promotion_lcb80"] == pytest.approx(0.10 - z_of(0.2) * 0.03, abs=1e-4)


def test_decay_needs_data_in_both_arms(db, eng):
    arm(db, "V2", 4000, 1000, start=NOW - DAY, ver=3)
    arm(db, "V1", 50, 40, start=NOW - DAY, ver=3)        # holdout too thin to judge
    dc = eng.decay_check(promoted(0.10, 0.02), NOW, [])
    assert dc["decayed"] == [] and "lift_now" not in dc["scopes"]["default"]


def test_rollback_plan(db, eng):
    e = promoted(0.10, 0.02)
    black = eng.plan_rollback(e, ["default"], NOW)
    assert black == ["V2"] and e.plan["default"] == {"V1": 1.0} and e.status == "rolling_back"


# ------------------------------------------------------------------ config sync / design
def _cfg(voice):
    return {"cohorts": [], "allocations": {"default": {"welcome_message": {"W1": 1.0}, "voice": voice,
                                                      "caller_id": {"D1": 1.0}}}, "prompt_version": "P1"}


def test_design_starts_when_live_and_supervisor_edit_aborts(eng):
    e = eng.design(WF, "voice", _cfg({"V1": 1.0}), ["V1", "V2", "V3"], {}, 0, 0.4, 2000)
    assert e.incumbent == "V1" and e.design["V1"] == pytest.approx(0.6)
    assert eng.on_config(e, _cfg({"V1": 1.0}), 2, "controller_approved", [], 10) is None   # not live yet
    assert eng.on_config(e, _cfg(dict(e.design)), 3, "controller_approved", ["voice"], 20) == "started"
    assert e.status == "running" and e.versions == [3] and e.start_minute == 20
    assert eng.on_config(e, _cfg(dict(e.design)), 4, "controller_auto", ["caller_id"], 30) == "versions"
    assert e.versions == [3, 4]
    assert eng.on_config(e, _cfg({"V2": 1.0}), 5, "supervisor", ["voice"], 40) == "aborted"
    assert e.status == "aborted"


def test_design_excludes_blacklisted_options_and_sizes_sample(eng):
    e = eng.design(WF, "voice", _cfg({"V1": 1.0}), ["V1", "V2", "V3"], {"V2": 10_000}, 0, 0.4, 2000)
    assert e.arms == ["V1", "V3"]
    # horizon cap: 2000 connected/day * 0.4 share * 5 days = 4000 per challenger at most
    assert Settings().min_arm_connected_for_look <= e.n_plan <= 4000
    assert e.achieved_mde > 0
    assert eng.design(WF, "voice", _cfg({"V1": 1.0}), ["V1", "V2"], {"V2": 10_000}, 0, 0.4, 2000) is None
